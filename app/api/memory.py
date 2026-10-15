from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.models import MemoryEvent, MemoryProfile, User
from app.services.auth import get_current_user
from app.services.graph import debug_graph
from app.services.memory import estimate_tokens
from app.services import hindsight, vector


router = APIRouter(prefix="/memory")
debug_router = APIRouter(prefix="/memory")


class MemoryEventUpdate(BaseModel):
    event_text: str | None = Field(default=None, min_length=1, max_length=500)
    importance: Literal["high", "mid", "low"] | None = None
    happened_at: date | None = None


def _serialize_event(event: MemoryEvent) -> dict:
    return {
        "id": event.id,
        "event_text": event.event_text,
        "importance": event.importance,
        "happened_at": event.happened_at,
        "source_conversation_id": event.source_conversation_id,
        "created_at": event.created_at,
    }


@router.get("/events")
def list_memory_events(
    include_deleted: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    filters = [MemoryEvent.user_id == user.id]
    if not include_deleted:
        filters.append(MemoryEvent.deleted == 0)
    events = session.scalars(
        select(MemoryEvent).where(*filters).order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc()).limit(limit)
    ).all()
    return {"events": [_serialize_event(event) for event in events]}


@router.patch("/events/{event_id}")
async def update_memory_event(
    event_id: int,
    request: MemoryEventUpdate,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    event = session.scalar(
        select(MemoryEvent).where(
            MemoryEvent.id == event_id,
            MemoryEvent.user_id == user.id,
            MemoryEvent.deleted == 0,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="memory event not found")
    changed_text = request.event_text is not None and request.event_text != event.event_text
    if request.event_text is not None:
        event.event_text = request.event_text.strip()
    if request.importance is not None:
        event.importance = request.importance
    if request.happened_at is not None:
        event.happened_at = request.happened_at
    warnings: list[str] = []
    session.commit()
    if changed_text:
        vector_id = event.vector_id or str(event.id)
        if not await vector.delete_event(vector_id):
            warnings.append("Milvus 向量删除失败")
        try:
            await vector.safe_add_event(event.id, event.event_text, event.importance, user.id)
        except Exception:
            warnings.append("Milvus 向量更新失败")
    result = _serialize_event(event)
    if warnings:
        result["warnings"] = warnings
    return result


@router.delete("/events/{event_id}")
async def delete_memory_event(
    event_id: int,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    event = session.scalar(
        select(MemoryEvent).where(
            MemoryEvent.id == event_id,
            MemoryEvent.user_id == user.id,
            MemoryEvent.deleted == 0,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="memory event not found")
    warnings: list[str] = []
    vector_id = event.vector_id or str(event.id)
    if not await vector.delete_event(vector_id):
        warnings.append("Milvus 向量删除失败")
    if event.hindsight_node_id and not await hindsight.delete_knowledge_node(event.hindsight_node_id, user.id):
        warnings.append("Hindsight 记忆删除失败")
    event.deleted = 1
    session.commit()
    return {"deleted": True, "id": event.id, "warnings": warnings}


@debug_router.get("/summary")
async def get_summary(session: Session = Depends(db.get_db), user: User = Depends(get_current_user)) -> dict:
    result = await debug_graph.ainvoke(
        {"operation": "summary"}, context={"db": session, "user_id": user.id}
    )
    return {"summary": result.get("summary"), "persona_snapshot": result.get("persona_snapshot")}


@debug_router.post("/compress")
async def compress(session: Session = Depends(db.get_db), user: User = Depends(get_current_user)) -> dict:
    result = await debug_graph.ainvoke(
        {"operation": "compress"}, context={"db": session, "user_id": user.id}
    )
    return {
        "compressed": result.get("changed", False),
        "before_tokens": result.get("before_tokens", 0),
        "after_tokens": result.get("after_tokens", 0),
    }


@debug_router.post("/reflect")
async def reflect(user: User = Depends(get_current_user), session: Session = Depends(db.get_db)) -> dict:
    return await debug_graph.ainvoke({"operation": "reflect"}, context={"db": session, "user_id": user.id})
