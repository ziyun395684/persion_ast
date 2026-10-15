from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import ChatMessage
from app.models import MemoryProfile


async def save_message(
    db: Session,
    role: str,
    content: str,
    intent: str | None = None,
    task_type: str | None = None,
    user_id: int = 1,
    conversation_id: int | None = None,
) -> ChatMessage:
    if role not in {"user", "assistant"}:
        raise ValueError("role must be 'user' or 'assistant'")

    current_max = db.scalar(
        select(func.max(ChatMessage.idx)).where(ChatMessage.user_id == user_id)
    )
    next_idx = (current_max or 0) + 1
    message = ChatMessage(
        idx=next_idx,
        user_id=user_id,
        role=role,
        content=content,
        intent=intent,
        task_type=task_type,
        conversation_id=conversation_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


async def recent_messages(
    db: Session,
    limit: int = 16,
    user_id: int = 1,
    conversation_id: int | None = None,
) -> list[ChatMessage]:
    if limit <= 0:
        return []

    filters = [ChatMessage.user_id == user_id]
    if conversation_id is not None:
        filters.append(ChatMessage.conversation_id == conversation_id)
    messages = db.scalars(
        select(ChatMessage)
        .where(*filters)
        .order_by(ChatMessage.idx.desc())
        .limit(limit)
    ).all()
    return list(reversed(messages))


async def increment_turn_count(db: Session, user_id: int = 1) -> int:
    return _update_profile_counter(db, MemoryProfile.turn_count, user_id)


async def reset_consecutive_task_turns(db: Session, user_id: int = 1) -> None:
    profile = db.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    if profile is None:
        raise RuntimeError("memory_profile id=1 does not exist")
    if profile.consecutive_task_turns == 0:
        return
    _update_profile(db, {MemoryProfile.consecutive_task_turns: 0}, user_id)


async def increment_consecutive_task_turns(db: Session, user_id: int = 1) -> int:
    return _update_profile_counter(db, MemoryProfile.consecutive_task_turns, user_id)


def _update_profile_counter(db: Session, counter_column, user_id: int) -> int:
    result = _update_profile(
        db,
        {
            counter_column: counter_column + 1,
        },
        user_id,
        returning_column=counter_column,
    )
    return result


def _update_profile(db: Session, values: dict, user_id: int, returning_column=None):
    values[MemoryProfile.profile_revision] = MemoryProfile.profile_revision + 1
    try:
        statement = (
            update(MemoryProfile)
            .where(MemoryProfile.user_id == user_id)
            .values(values)
        )
        if returning_column is not None:
            if db.execute(statement).rowcount != 1:
                raise RuntimeError(f"memory_profile user_id={user_id} does not exist")
            result = db.scalar(
                select(returning_column).where(MemoryProfile.user_id == user_id)
            )
        else:
            result = None
            if db.execute(statement).rowcount != 1:
                raise RuntimeError(f"memory_profile user_id={user_id} does not exist")
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
