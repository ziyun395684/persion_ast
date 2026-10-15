import asyncio
import logging
from time import perf_counter
from typing import Awaitable, Callable, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import CFG
from app.models import Conversation, MemoryProfile
from app.services import forget as forget_service
from app.services import reflection
from app.services import memory, model, polish as polish_service, style as style_service, vector
from app.services.message import (
    increment_consecutive_task_turns,
    increment_turn_count,
    reset_consecutive_task_turns,
    save_message,
)
from app.services import intent
from app.services.orchestrator import build_prompt_context
from app.tools import todo
from app.tools import note, time, web


logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("uvicorn.error")


def _log_chat_stage(stage: str, started: float) -> None:
    elapsed_ms = (perf_counter() - started) * 1000
    message = "chat_stage stage=%s elapsed_ms=%.1f"
    logger.info(message, stage, elapsed_ms)
    timing_logger.info(message, stage, elapsed_ms)


class GraphContext(TypedDict, total=False):
    db: Session
    user_id: int
    conversation_id: int | None
    stream_callback: Callable[[str], Awaitable[None]]


class ChatState(TypedDict, total=False):
    user_msg: str
    conversation_id: int | None
    prefetched_recalled: list[dict]
    flush_ok: bool
    user_message_id: int
    assistant_message_id: int
    turn_count: int
    prompt: list[dict[str, str]]
    reply: str
    intent: str
    task_type: str
    also_chat: bool
    reasoning: str
    recalled_events: list[dict]
    l2_summary: str | None
    style_preset: str
    tool_args: dict


class MemoryState(TypedDict, total=False):
    operation: str
    changed: bool
    processed: int
    flushed: bool


class JobsState(TypedDict, total=False):
    operation: str
    processed: int
    retried: bool


class DebugState(TypedDict, total=False):
    operation: str
    summary: str | None
    persona_snapshot: str | None
    changed: bool
    before_tokens: int
    after_tokens: int
    status: str
    message: str


class TodoState(TypedDict, total=False):
    operation: str
    content: str
    due_date: str | None
    status: str | None
    todo_id: int
    ok: bool
    data: object
    error: str | None


class NoteState(TypedDict, total=False):
    operation: str
    content: str
    query: str
    k: int
    ok: bool
    data: object
    error: str | None


class TimeState(TypedDict, total=False):
    operation: str
    ok: bool
    data: str
    error: str | None


class WebState(TypedDict, total=False):
    query: str
    ok: bool
    answer: str


class PolishState(TypedDict, total=False):
    task_name: str
    raw_result: object
    also_chat: bool
    recalled_events: list[dict]
    l2_summary: str | None
    reply: str


class ForgetState(TypedDict, total=False):
    user_msg: str
    reply: str


TASK_COMPANION_NUDGE = "哥哥一直在忙，要不要歇会儿跟我唠两句？"


class StyleState(TypedDict, total=False):
    style_preset: str
    user_msg: str
    conversation_id: int | None
    reply: str


def get_db(runtime: Runtime[GraphContext]) -> Session:
    if not runtime.context or runtime.context.get("db") is None:
        raise ValueError("LangGraph runtime context requires a database session")
    return runtime.context["db"]


def get_user_id(runtime: Runtime[GraphContext]) -> int:
    if not runtime.context:
        raise ValueError("LangGraph runtime context requires a user_id")
    return int(runtime.context.get("user_id", 1))


def get_conversation_id(runtime: Runtime[GraphContext]) -> int | None:
    if not runtime.context:
        return None
    value = runtime.context.get("conversation_id")
    return int(value) if value is not None else None


async def flush_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    started = perf_counter()
    try:
        return {"flush_ok": await memory.flush_pending_with_timeout(get_db(runtime), user_id=get_user_id(runtime))}
    finally:
        _log_chat_stage("flush", started)


async def persist_user_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    started = perf_counter()
    db = get_db(runtime)
    user_id = get_user_id(runtime)
    message = await save_message(
        db,
        "user",
        state["user_msg"],
        user_id=user_id,
        conversation_id=get_conversation_id(runtime),
    )
    try:
        return {
            "user_message_id": message.id,
            "turn_count": await increment_turn_count(db, user_id),
        }
    finally:
        _log_chat_stage("persist_user", started)


async def classify_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    started = perf_counter()
    user_msg = state["user_msg"]
    user_id = get_user_id(runtime)
    classification_task = asyncio.create_task(intent.classify(user_msg))
    retrieval_task = asyncio.create_task(
        vector.search(
            user_msg,
            k=min(CFG.recall_top_k, 2),
            min_score=CFG.recall_min_score,
            user_id=user_id,
        )
    )
    classification, recalled = await asyncio.gather(
        classification_task, retrieval_task, return_exceptions=True
    )
    if isinstance(classification, Exception):
        raise classification
    if isinstance(recalled, Exception):
        logger.warning("parallel vector retrieval failed: %s", type(recalled).__name__)
        recalled = []
    style_preset = await intent.detect_style_switch(
        user_msg, classification
    )
    if style_preset is not None:
        classification = {
            **classification,
            "intent": "style_switch",
            "task_type": "none",
            "style_preset": style_preset,
        }
    result = {**classification, "prefetched_recalled": recalled}
    _log_chat_stage("classify", started)
    return result


def classify_route(state: ChatState) -> str:
    if state.get("intent") == "style_switch":
        return "style"
    return "forget" if state.get("intent") == "forget" else "prompt"


async def prompt_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    started = perf_counter()
    needs_memory = state.get("intent") in {"chat", "forget"} or state.get("also_chat", False)
    context = await build_prompt_context(
        get_db(runtime),
        state["user_msg"],
        user_id=get_user_id(runtime),
        include_recall=needs_memory and state.get("flush_ok", True),
        conversation_id=get_conversation_id(runtime),
        prefetched_recalled=state.get("prefetched_recalled") if needs_memory else [],
        include_hindsight=needs_memory,
    )
    _log_chat_stage("prompt", started)
    return context


def prompt_route(state: ChatState) -> str:
    if state.get("intent") == "task" and state.get("task_type") in {
        "weather",
        "calendar",
    }:
        return "unsupported"
    if state.get("intent") == "task" and state.get("task_type") in {
        "todo",
        "note",
        "search",
        "time",
    }:
        return "tool"
    return "model"


async def model_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    started = perf_counter()
    try:
        callback = runtime.context.get("stream_callback") if runtime.context else None
        if callback is None:
            reply = await model.chat(
                state["prompt"],
                max_tokens=CFG.main_model_max_tokens,
                temperature=CFG.temperature["main_chat"],
                timeout=CFG.model_timeout_sec,
                enable_thinking=False,
            )
        else:
            deltas = []
            async for delta in model.stream_chat(
                state["prompt"],
                max_tokens=CFG.main_model_max_tokens,
                temperature=CFG.temperature["main_chat"],
                timeout=CFG.model_timeout_sec,
                enable_thinking=False,
            ):
                deltas.append(delta)
                await callback(delta)
            reply = "".join(deltas)
            if not reply.strip():
                raise model.ModelError("streaming model returned an empty response")
    except (model.ModelError, httpx.TimeoutException):
        reply = "哥哥等我一下，我这边有点卡壳，再说一次好不好～"
    _log_chat_stage("model", started)
    return {"reply": reply}


async def forget_chat_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    return {"reply": await forget_service._forget_impl(get_db(runtime), state["user_msg"], get_user_id(runtime))}


async def style_chat_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    result = await style_service.switch_style(
        get_db(runtime), state["style_preset"], state["user_msg"], get_user_id(runtime), get_conversation_id(runtime)
    )
    return result


async def unsupported_task_node(state: ChatState) -> dict:
    return {
        "reply": await polish_service._polish_impl(
            "未知工具",
            "",
            state.get("also_chat", False),
            state.get("recalled_events", []),
            state.get("l2_summary"),
        )
    }


def _fallback_tool_args(state: ChatState) -> dict:
    user_msg = state.get("user_msg", "").strip()
    task_type = state.get("task_type")
    args = state.get("tool_args") if isinstance(state.get("tool_args"), dict) else {}
    if task_type == "todo":
        if args:
            return args
        if any(keyword in user_msg for keyword in ("我的待办", "待办列表", "有哪些待办")):
            return {"operation": "list"}
        return {
            "operation": "add",
            "content": user_msg.removeprefix("帮我记一下").removeprefix("记一下").strip(),
        }
    if task_type == "note":
        if args:
            return args
        operation = "recall" if any(keyword in user_msg for keyword in ("上次", "之前", "记得")) else "save"
        return {"operation": operation, "query" if operation == "recall" else "content": user_msg}
    if task_type == "search":
        return args or {"query": user_msg}
    return args


async def tool_task_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    db = get_db(runtime)
    user_id = get_user_id(runtime)
    task_type = state.get("task_type")
    args = _fallback_tool_args(state)
    if task_type == "todo":
        operation = args.get("operation", "add")
        if operation == "list":
            raw_result = await todo._todo_list_impl(db, args.get("status"), user_id)
        elif operation == "done":
            raw_result = await todo._todo_done_impl(db, args.get("todo_id"), user_id)
        else:
            raw_result = await todo._todo_add_impl(db, args.get("content", ""), args.get("due_date"), user_id)
        task_name = {"add": "新增待办", "list": "查询待办", "done": "完成待办"}.get(operation, "处理待办")
    elif task_type == "note":
        operation = args.get("operation", "save")
        if operation == "recall":
            raw_result = await note._note_recall_impl(db, args.get("query", state.get("user_msg", "")), args.get("k", 3), user_id)
            task_name = "回忆笔记"
        else:
            raw_result = await note._note_save_impl(db, args.get("content", state.get("user_msg", "")), user_id)
            task_name = "保存笔记"
    elif task_type == "search":
        raw_result = await web._web_query_impl(args.get("query", state.get("user_msg", "")))
        task_name = "联网查询"
    else:
        raw_result = time._time_now_impl()
        task_name = "查询时间"

    polished = await polish_graph.ainvoke(
        {
            "task_name": task_name,
            "raw_result": raw_result,
            "also_chat": state.get("also_chat", False),
            "recalled_events": state.get("recalled_events", []),
            "l2_summary": state.get("l2_summary"),
        }
    )
    return {"reply": polished.get("reply", "")}


async def persist_assistant_node(state: ChatState, runtime: Runtime[GraphContext]) -> dict:
    started = perf_counter()
    db = get_db(runtime)
    user_id = get_user_id(runtime)
    reply = state["reply"]
    if state.get("intent") == "task":
        profile = db.get(MemoryProfile, 1)
        previous_task_turns = profile.consecutive_task_turns if profile else 0
        await increment_consecutive_task_turns(db, user_id)
        if previous_task_turns >= CFG.consecutive_task_nudge:
            reply = f"{reply}{TASK_COMPANION_NUDGE}"
    else:
        await reset_consecutive_task_turns(db, user_id)

    assistant = await save_message(
        db,
        "assistant",
        reply,
        user_id=user_id,
        conversation_id=get_conversation_id(runtime),
    )
    conversation_id = get_conversation_id(runtime)
    if conversation_id is not None:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is not None:
            conversation.updated_at = func.now()
            db.commit()
    await memory.mark_extract_pending(db, [state["user_message_id"], assistant.id], user_id)
    result = {"assistant_message_id": assistant.id, "reply": reply}
    _log_chat_stage("persist_assistant", started)
    return result


def build_chat_graph():
    graph = StateGraph(ChatState, context_schema=GraphContext)
    graph.add_node("flush", flush_node)
    graph.add_node("persist_user", persist_user_node)
    graph.add_node("classify", classify_node)
    graph.add_node("prompt", prompt_node)
    graph.add_node("model", model_node)
    graph.add_node("forget", forget_chat_node)
    graph.add_node("style", style_chat_node)
    graph.add_node("unsupported", unsupported_task_node)
    graph.add_node("tool", tool_task_node)
    graph.add_node("persist_assistant", persist_assistant_node)
    graph.add_edge(START, "flush")
    graph.add_edge("flush", "persist_user")
    graph.add_edge("persist_user", "classify")
    graph.add_conditional_edges("classify", classify_route)
    graph.add_conditional_edges("prompt", prompt_route)
    graph.add_edge("model", "persist_assistant")
    graph.add_edge("forget", "persist_assistant")
    graph.add_edge("style", "persist_assistant")
    graph.add_edge("unsupported", "persist_assistant")
    graph.add_edge("tool", "persist_assistant")
    graph.add_edge("persist_assistant", END)
    return graph.compile()


chat_graph = build_chat_graph()


async def style_node(state: StyleState, runtime: Runtime[GraphContext]) -> dict:
    return await style_service.switch_style(
        get_db(runtime), state["style_preset"], state.get("user_msg", ""), get_user_id(runtime), get_conversation_id(runtime)
    )


def build_style_graph():
    graph = StateGraph(StyleState, context_schema=GraphContext)
    graph.add_node("style", style_node)
    graph.add_edge(START, "style")
    graph.add_edge("style", END)
    return graph.compile()


style_graph = build_style_graph()


async def memory_summarize_node(
    state: MemoryState, runtime: Runtime[GraphContext]
) -> dict:
    return {"changed": await memory._summarize_impl(get_db(runtime), get_user_id(runtime))}


async def memory_extract_node(
    state: MemoryState, runtime: Runtime[GraphContext]
) -> dict:
    processed = await memory._extract_pending_events_impl(get_db(runtime), get_user_id(runtime))
    return {"processed": processed}


async def memory_flush_node(
    state: MemoryState, runtime: Runtime[GraphContext]
) -> dict:
    flushed = await memory._flush_pending_impl(get_db(runtime), user_id=get_user_id(runtime))
    return {
        "flushed": flushed is not False,
        "processed": flushed if flushed is not False else 0,
    }


def memory_route(state: MemoryState) -> str:
    return {
        "summarize": "summarize",
        "extract": "extract",
        "flush": "flush",
    }.get(state.get("operation", "summarize"), "summarize")


def build_memory_graph():
    graph = StateGraph(MemoryState, context_schema=GraphContext)
    graph.add_node("summarize", memory_summarize_node)
    graph.add_node("extract", memory_extract_node)
    graph.add_node("flush", memory_flush_node)
    graph.add_conditional_edges(START, memory_route)
    graph.add_edge("summarize", END)
    graph.add_edge("extract", END)
    graph.add_edge("flush", END)
    return graph.compile()


memory_graph = build_memory_graph()


async def jobs_extract_node(
    state: JobsState, runtime: Runtime[GraphContext]
) -> dict:
    db = get_db(runtime)
    try:
        processed = await memory.extract_pending_events(db, get_user_id(runtime))
    except TypeError as exc:
        if "positional" not in str(exc) and "user_id" not in str(exc):
            raise
        processed = await memory.extract_pending_events(db)
    return {"processed": processed}


async def jobs_retry_node(state: JobsState) -> dict:
    await vector.retry_pending()
    return {"retried": True}


def jobs_route(state: JobsState) -> str:
    return "retry" if state.get("operation") == "vector_retry" else "extract"


def build_jobs_graph():
    graph = StateGraph(JobsState, context_schema=GraphContext)
    graph.add_node("extract", jobs_extract_node)
    graph.add_node("retry", jobs_retry_node)
    graph.add_conditional_edges(START, jobs_route)
    graph.add_edge("extract", END)
    graph.add_edge("retry", END)
    return graph.compile()


jobs_graph = build_jobs_graph()


async def debug_summary_node(
    state: DebugState, runtime: Runtime[GraphContext]
) -> dict:
    profile = get_db(runtime).scalar(select(MemoryProfile).where(MemoryProfile.user_id == get_user_id(runtime)))
    return {
        "summary": profile.summary if profile else None,
        "persona_snapshot": profile.persona_snapshot if profile else None,
    }


async def debug_compress_node(
    state: DebugState, runtime: Runtime[GraphContext]
) -> dict:
    db = get_db(runtime)
    user_id = get_user_id(runtime)
    before_profile = db.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    before = memory.estimate_tokens(before_profile.summary if before_profile else None)
    changed = await memory._summarize_impl(db, user_id)
    after_profile = db.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    after = memory.estimate_tokens(after_profile.summary if after_profile else None)
    return {"changed": changed, "before_tokens": before, "after_tokens": after}


async def debug_reflect_node(
    _: DebugState, runtime: Runtime[GraphContext]
) -> dict:
    await reflection._reflect_impl(get_db(runtime), get_user_id(runtime))
    return {"status": "completed"}


def debug_route(state: DebugState) -> str:
    return {
        "summary": "summary",
        "compress": "compress",
        "reflect": "reflect",
    }.get(state.get("operation", "summary"), "summary")


def build_debug_graph():
    graph = StateGraph(DebugState, context_schema=GraphContext)
    graph.add_node("summary", debug_summary_node)
    graph.add_node("compress", debug_compress_node)
    graph.add_node("reflect", debug_reflect_node)
    graph.add_conditional_edges(START, debug_route)
    graph.add_edge("summary", END)
    graph.add_edge("compress", END)
    graph.add_edge("reflect", END)
    return graph.compile()


debug_graph = build_debug_graph()


async def todo_add_node(state: TodoState, runtime: Runtime[GraphContext]) -> dict:
    return await todo._todo_add_impl(
        get_db(runtime), state.get("content", ""), state.get("due_date")
    )


async def todo_list_node(state: TodoState, runtime: Runtime[GraphContext]) -> dict:
    return await todo._todo_list_impl(get_db(runtime), state.get("status"))


async def todo_done_node(state: TodoState, runtime: Runtime[GraphContext]) -> dict:
    return await todo._todo_done_impl(get_db(runtime), state.get("todo_id"))


def todo_route(state: TodoState) -> str:
    return {
        "add": "add",
        "list": "list",
        "done": "done",
    }.get(state.get("operation", "list"), "list")


def build_todo_graph():
    graph = StateGraph(TodoState, context_schema=GraphContext)
    graph.add_node("add", todo_add_node)
    graph.add_node("list", todo_list_node)
    graph.add_node("done", todo_done_node)
    graph.add_conditional_edges(START, todo_route)
    graph.add_edge("add", END)
    graph.add_edge("list", END)
    graph.add_edge("done", END)
    return graph.compile()


todo_graph = build_todo_graph()


async def note_save_node(state: NoteState, runtime: Runtime[GraphContext]) -> dict:
    return await note._note_save_impl(
        get_db(runtime), state.get("content", ""), get_user_id(runtime)
    )


async def note_recall_node(state: NoteState, runtime: Runtime[GraphContext]) -> dict:
    return await note._note_recall_impl(
        get_db(runtime), state.get("query", ""), state.get("k", 3), get_user_id(runtime)
    )


def note_route(state: NoteState) -> str:
    return "recall" if state.get("operation") == "recall" else "save"


def build_note_graph():
    graph = StateGraph(NoteState, context_schema=GraphContext)
    graph.add_node("save", note_save_node)
    graph.add_node("recall", note_recall_node)
    graph.add_conditional_edges(START, note_route)
    graph.add_edge("save", END)
    graph.add_edge("recall", END)
    return graph.compile()


note_graph = build_note_graph()


def time_now_node(_: TimeState) -> dict:
    return time._time_now_impl()


def build_time_graph():
    graph = StateGraph(TimeState)
    graph.add_node("now", time_now_node)
    graph.add_edge(START, "now")
    graph.add_edge("now", END)
    return graph.compile()


time_graph = build_time_graph()


async def web_query_node(state: WebState) -> dict:
    return await web._web_query_impl(state.get("query", ""))


def build_web_graph():
    graph = StateGraph(WebState)
    graph.add_node("query", web_query_node)
    graph.add_edge(START, "query")
    graph.add_edge("query", END)
    return graph.compile()


web_graph = build_web_graph()


async def polish_node(state: PolishState) -> dict:
    return {
        "reply": await polish_service._polish_impl(
            state.get("task_name", "助手任务"),
            state.get("raw_result"),
            state.get("also_chat", False),
            state.get("recalled_events", []),
            state.get("l2_summary"),
        )
    }


def build_polish_graph():
    graph = StateGraph(PolishState)
    graph.add_node("polish", polish_node)
    graph.add_edge(START, "polish")
    graph.add_edge("polish", END)
    return graph.compile()


polish_graph = build_polish_graph()


async def forget_node(
    state: ForgetState, runtime: Runtime[GraphContext]
) -> dict:
    return {"reply": await forget_service._forget_impl(get_db(runtime), state.get("user_msg", ""))}


def build_forget_graph():
    graph = StateGraph(ForgetState, context_schema=GraphContext)
    graph.add_node("forget", forget_node)
    graph.add_edge(START, "forget")
    graph.add_edge("forget", END)
    return graph.compile()


forget_graph = build_forget_graph()


async def reflection_node(
    _: MemoryState, runtime: Runtime[GraphContext]
) -> dict:
    await reflection._reflect_impl(get_db(runtime))
    return {"status": "completed"}


def build_reflection_graph():
    graph = StateGraph(MemoryState, context_schema=GraphContext)
    graph.add_node("reflect", reflection_node)
    graph.add_edge(START, "reflect")
    graph.add_edge("reflect", END)
    return graph.compile()


reflection_graph = build_reflection_graph()
