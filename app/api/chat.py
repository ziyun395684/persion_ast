import asyncio
import json
import logging
from time import perf_counter

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app import db
from app.config import CFG
from app.services import model  # compatibility injection point for tests/callers
from app.services import hindsight
from app.services.lock import get_user_lock
from app.services.graph import chat_graph
from app.services.auth import get_current_user
from app.models import ChatMessage, Conversation, User
from sqlalchemy import select


router = APIRouter()
logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("uvicorn.error")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: int | None = Field(default=None, gt=0)


async def _run_chat(
    request: ChatRequest,
    session: Session,
    user_id: int,
    stream_callback=None,
) -> dict:
    started = perf_counter()
    async with get_user_lock(user_id):
        try:
            context = {
                "db": session,
                "user_id": user_id,
                "conversation_id": request.conversation_id,
            }
            if stream_callback is not None:
                context["stream_callback"] = stream_callback
            return await chat_graph.ainvoke(
                {"user_msg": request.message, "conversation_id": request.conversation_id},
                context=context,
            )
        finally:
            message = "chat_total user_id=%s conversation_id=%s elapsed_ms=%.1f"
            values = (
                user_id,
                request.conversation_id,
                (perf_counter() - started) * 1000,
            )
            logger.info(message, *values)
            timing_logger.info(message, *values)


def _validate_conversation(
    session: Session, user_id: int, conversation_id: int | None
) -> None:
    if conversation_id is None:
        return
    item = session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.archived == 0,
        )
    )
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="conversation not found")


def _schedule_retain(
    background_tasks: BackgroundTasks, request: ChatRequest, result: dict, user_id: int
) -> None:
    retain_kwargs = {
        "content": f"用户：{request.message}\n小玉：{result['reply']}",
        "context": "日常对话",
        "tags": ["source:chat"],
        "document_id": f"chat-{result['assistant_message_id']}",
        "user_id": user_id,
    }
    if request.conversation_id:
        retain_kwargs["metadata"] = {"conversation_id": str(request.conversation_id)}
    background_tasks.add_task(
        hindsight.retain,
        **retain_kwargs,
    )


def _sse_event(event: str, payload: dict) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


@router.post("/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _validate_conversation(session, user.id, request.conversation_id)
    result = await _run_chat(request, session, user.id)

    response = {"reply": result["reply"]}
    _schedule_retain(background_tasks, request, result, user.id)
    if CFG.debug:
        response["debug"] = {
            "prompt_messages": len(result.get("prompt", [])),
            "turn_count": result.get("turn_count"),
        }
    return response


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    _validate_conversation(session, user.id, request.conversation_id)

    async def event_stream():
        yield _sse_event("status", {"status": "thinking"})
        queue: asyncio.Queue[str] = asyncio.Queue()
        streamed = False

        async def on_delta(delta: str) -> None:
            nonlocal streamed
            streamed = True
            await queue.put(_sse_event("delta", {"delta": delta}))

        task = asyncio.create_task(_run_chat(request, session, user.id, on_delta))
        try:
            while not task.done() or not queue.empty():
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
            result = await task
        except Exception as exc:
            logger.warning(
                "chat stream failed user_id=%s conversation_id=%s error=%s",
                user.id,
                request.conversation_id,
                type(exc).__name__,
                exc_info=True,
            )
            yield _sse_event("done", {"done": True, "error": True})
            return
        _schedule_retain(background_tasks, request, result, user.id)
        reply = result.get("reply", "")
        if not streamed:
            chunk_size = max(1, CFG.stream_chunk_chars)
            for index in range(0, len(reply), chunk_size):
                yield _sse_event("delta", {"delta": reply[index : index + chunk_size]})
                if index + chunk_size < len(reply):
                    await asyncio.sleep(max(0, CFG.stream_chunk_delay_ms) / 1000)
        yield _sse_event("done", {"done": True})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=background_tasks,
    )


@router.get("/chat/history")
def chat_history(
    limit: int = Query(default=50, ge=1, le=200),
    conversation_id: int | None = Query(default=None, gt=0),
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _validate_conversation(session, user.id, conversation_id)
    filters = [ChatMessage.user_id == user.id]
    if conversation_id is not None:
        filters.append(ChatMessage.conversation_id == conversation_id)
    messages = session.scalars(
        select(ChatMessage)
        .where(*filters)
        .order_by(ChatMessage.idx.asc())
        .limit(limit)
    ).all()
    return {
        "messages": [
            {"id": item.id, "role": item.role, "content": item.content, "created_at": item.created_at}
            for item in messages
        ]
    }
