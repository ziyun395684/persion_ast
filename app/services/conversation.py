from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, Conversation, MemoryEvent
from app.services import hindsight, vector


logger = logging.getLogger(__name__)


def _get_conversation(db: Session, user_id: int, conversation_id: int) -> Conversation | None:
    return db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )


async def delete_conversation(
    db: Session,
    user_id: int,
    conversation_id: int,
    *,
    forget: bool = False,
) -> dict:
    conversation = _get_conversation(db, user_id, conversation_id)
    if conversation is None:
        return {"found": False}

    memories = []
    warnings: list[str] = []
    if forget:
        memories = db.scalars(
            select(MemoryEvent).where(
                MemoryEvent.user_id == user_id,
                MemoryEvent.source_conversation_id == conversation_id,
                MemoryEvent.deleted == 0,
            )
        ).all()
        for memory in memories:
            if memory.vector_id and not await vector.delete_event(memory.vector_id):
                warnings.append(f"Milvus memory deletion failed: {memory.id}")
            if memory.hindsight_node_id:
                if not await hindsight.delete_knowledge_node(memory.hindsight_node_id, user_id):
                    warnings.append(f"Hindsight memory deletion failed: {memory.id}")

    try:
        with db.begin_nested():
            db.execute(
                delete(ChatMessage).where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.conversation_id == conversation_id,
                )
            )
            if forget and memories:
                db.execute(
                    delete(MemoryEvent).where(
                        MemoryEvent.user_id == user_id,
                        MemoryEvent.source_conversation_id == conversation_id,
                    )
                )
            db.delete(conversation)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "found": True,
        "deleted": True,
        "forgotten": len(memories) if forget else 0,
        "warnings": warnings,
    }
