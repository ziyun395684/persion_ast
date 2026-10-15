import logging
import json
import asyncio
from datetime import date
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import CFG
from app.models import ChatMessage, MemoryEvent, MemoryProfile
from app.services import model
from app.services import vector


logger = logging.getLogger(__name__)

_IMPORTANCE_ALIASES = {
    "medium": "mid",
    "middle": "mid",
    "中": "mid",
    "高": "high",
    "低": "low",
}


SUMMARY_PROMPT = """你在帮一个 AI 女友整理她和男朋友的相处记忆。
请阅读【旧摘要】+【新对话】，输出一份合并后的新摘要，要求：
1. 只保留“以后对话还有用”的信息：用户偏好、作息、人际关系、近期压力、讨厌的点、你们之间的小约定。
2. 丢弃寒暄、无信息量的内容。
3. 用第三人称写（“哥哥喜欢…”），不要写成聊天记录。
4. 总长控制在 300 字以内。

【旧摘要】{old_summary}
【新对话】{new_dialogue}
"""


def estimate_tokens(text: str | None) -> int:
    return int(len(text or "") / 1.5)


async def get_pending_queue(db: Session, user_id: int = 1) -> list[ChatMessage]:
    total = db.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.user_id == user_id)
    ) or 0
    if total <= CFG.short_window_messages:
        return []

    window = (
        select(ChatMessage.idx).where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.idx.desc())
        .limit(CFG.short_window_messages)
        .subquery()
    )
    window_min = select(func.min(window.c.idx)).scalar_subquery()
    return db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id, ChatMessage.is_compressed == 0, ChatMessage.idx <= window_min)
        .order_by(ChatMessage.idx.asc())
    ).all()


async def _summarize_impl(db: Session, user_id: int = 1) -> bool:
    pending = await get_pending_queue(db, user_id)
    profile = db.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    if profile is None:
        return False

    now = datetime.now(timezone.utc)
    summary_is_old = (
        profile.updated_at is None
        or _as_utc(profile.updated_at) <= now - timedelta(minutes=CFG.summary_min_interval_min)
    )
    should_trigger = len(pending) >= CFG.summary_trigger_queue or (
        estimate_tokens(profile.summary) >= CFG.summary_max_tokens and summary_is_old
    )
    if not should_trigger or not pending:
        return False
    base_revision = profile.profile_revision

    dialogue = "\n".join(f"{item.role}: {item.content}" for item in pending)
    prompt = SUMMARY_PROMPT.format(old_summary=profile.summary or "（无）", new_dialogue=dialogue)
    try:
        summary = await model.small_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=CFG.summary_max_output_tokens,
            temperature=CFG.temperature["summary"],
        )
    except Exception:
        logger.exception("summary generation failed")
        return False

    summary = _truncate_summary(summary)
    before_tokens = estimate_tokens(profile.summary)
    after_tokens = estimate_tokens(summary)
    logger.info("summary tokens before=%d after=%d", before_tokens, after_tokens)
    try:
        current_revision = db.scalar(
            select(MemoryProfile.profile_revision).where(MemoryProfile.user_id == user_id)
        )
        if current_revision != base_revision:
            logger.warning("summary writeback skipped due to profile revision conflict")
            return False
        db.execute(
            update(MemoryProfile)
            .where(MemoryProfile.user_id == user_id)
            .values(
                summary=summary,
                updated_at=func.now(),
                profile_revision=MemoryProfile.profile_revision + 1,
            )
        )
        db.execute(
            update(ChatMessage)
            .where(ChatMessage.user_id == user_id, ChatMessage.id.in_([item.id for item in pending]))
            .values(is_compressed=1)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


async def check_and_trigger_summary(db: Session, user_id: int = 1) -> None:
    await summarize(db, user_id)


async def summarize(db: Session, user_id: int = 1) -> bool:
    from app.services.graph import memory_graph

    result = await memory_graph.ainvoke(
        {"operation": "summarize"}, context={"db": db, "user_id": user_id}
    )
    return bool(result.get("changed", False))


async def mark_extract_pending(db: Session, message_ids: list[int], user_id: int = 1) -> None:
    if not message_ids:
        return
    db.execute(
        update(ChatMessage)
        .where(ChatMessage.user_id == user_id, ChatMessage.id.in_(message_ids))
        .values(extract_pending=1)
    )
    db.commit()


async def _extract_pending_events_impl(db: Session, user_id: int = 1) -> int:
    pending = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id, ChatMessage.extract_pending == 1)
        .order_by(ChatMessage.idx.asc())
    ).all()
    processed = 0
    for message_item in pending:
        prompt = (
            "只抽取客观事实、计划、承诺、具体偏好。输出 JSON 数组，每条包含 event、time、importance。"
            "情绪、寒暄和即时评价必须标记 low。\n"
            f"对话：{message_item.content}"
        )
        try:
            raw = await asyncio.wait_for(
                model.small_chat(
                    [{"role": "user", "content": prompt}],
                    max_tokens=CFG.extract_max_output_tokens,
                    temperature=CFG.temperature["extract"],
                ),
                timeout=CFG.model_timeout_sec,
            )
            events = _parse_events(raw)
            for item in events:
                if item.get("importance") == "low" or not item.get("event"):
                    continue
                event = MemoryEvent(
                    user_id=user_id,
                    source_conversation_id=message_item.conversation_id,
                    event_text=str(item["event"])[: CFG.event_text_max_chars],
                    importance=_normalize_importance(item.get("importance")),
                    happened_at=_parse_date(item.get("time")),
                )
                db.add(event)
                db.flush()
                await vector.safe_add_event(event.id, event.event_text, event.importance, user_id)
            message_item.extract_pending = 0
            db.commit()
            processed += 1
        except Exception as exc:
            db.rollback()
            logger.warning(
                "event extraction failed idx=%s error=%s detail=%s",
                message_item.idx,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
    return processed


async def _flush_pending_impl(db: Session, timeout: int | None = None, user_id: int = 1) -> int | bool:
    try:
        processed = await __import__("asyncio").wait_for(
            _extract_for_user(db, user_id),
            timeout=CFG.extract_flush_timeout_sec if timeout is None else timeout,
        )
        return processed
    except Exception:
        logger.exception("pending event flush failed")
    return False


async def _extract_for_user(db: Session, user_id: int) -> int:
    try:
        return await extract_pending_events(db, user_id)
    except TypeError as exc:
        if "positional" not in str(exc) and "user_id" not in str(exc):
            raise
        return await extract_pending_events(db)


async def extract_pending_events(db: Session, user_id: int = 1) -> int:
    from app.services.graph import memory_graph

    result = await memory_graph.ainvoke(
        {"operation": "extract"}, context={"db": db, "user_id": user_id}
    )
    return int(result.get("processed", 0))


async def flush_pending_with_timeout(db: Session, timeout: int | None = None, user_id: int = 1) -> bool:
    from app.services.graph import memory_graph

    if timeout is None:
        result = await memory_graph.ainvoke(
            {"operation": "flush"}, context={"db": db, "user_id": user_id}
        )
        return bool(result.get("flushed", False))
    try:
        result = await asyncio.wait_for(
            memory_graph.ainvoke(
                {"operation": "flush"}, context={"db": db, "user_id": user_id}
            ),
            timeout=timeout,
        )
        return bool(result.get("flushed", False))
    except Exception:
        logger.exception("pending event flush failed")
        return False


def _parse_events(raw: str) -> list[dict]:
    cleaned = raw.strip().removeprefix("```").removesuffix("```").strip()
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()
    value = json.loads(cleaned)
    return value if isinstance(value, list) else []


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _normalize_importance(value: object) -> str:
    normalized = str(value or "mid").strip().lower()
    normalized = _IMPORTANCE_ALIASES.get(normalized, normalized)
    return normalized if normalized in {"high", "mid", "low"} else "mid"


def _truncate_summary(summary: str) -> str:
    max_chars = int((CFG.summary_max_tokens - 1) * 1.5)
    return summary[:max_chars]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
