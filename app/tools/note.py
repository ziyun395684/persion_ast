from sqlalchemy.orm import Session

from app.models import Note
from app.services import vector


def _success(data):
    return {"ok": True, "data": data, "error": None}


def _error(message: str):
    return {"ok": False, "data": None, "error": message}


def _serialize(note: Note) -> dict:
    return {
        "id": note.id,
        "content": note.content,
        "importance": note.importance,
        "tags": note.tags,
        "vector_id": note.vector_id,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


async def _note_save_impl(db: Session, content: str, user_id: int = 1) -> dict:
    content = content.strip() if isinstance(content, str) else ""
    if not content:
        return _error("content cannot be empty")
    note = Note(user_id=user_id, content=content, importance="mid")
    try:
        db.add(note)
        db.flush()
        note.vector_id = str(note.id)
        db.commit()
        db.refresh(note)
        await vector.safe_add_note(note.id, note.content, note.importance, user_id)
    except Exception:
        db.rollback()
        return _error("failed to save note")
    return _success(_serialize(note))


async def _note_recall_impl(db: Session, query: str, k: int = 3, user_id: int = 1) -> dict:
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        return _error("query cannot be empty")
    try:
        limit = int(k)
    except (TypeError, ValueError):
        return _error("k must be an integer")
    if limit <= 0:
        return _error("k must be greater than zero")
    try:
        matches = await vector.search_notes(query, k=limit, user_id=user_id)
    except Exception:
        return _error("failed to recall notes")
    data = [
        {
            "id": str(item["id"]),
            "content": item.get("text", ""),
            "similarity": item.get("similarity"),
        }
        for item in matches
    ]
    return _success(data)


async def note_save(db: Session, content: str, user_id: int = 1) -> dict:
    from app.services.graph import note_graph

    result = await note_graph.ainvoke(
        {"operation": "save", "content": content},
        context={"db": db, "user_id": user_id},
    )
    return {key: result.get(key) for key in ("ok", "data", "error")}


async def note_recall(db: Session, query: str, k: int = 3, user_id: int = 1) -> dict:
    from app.services.graph import note_graph

    result = await note_graph.ainvoke(
        {"operation": "recall", "query": query, "k": k},
        context={"db": db, "user_id": user_id},
    )
    return {key: result.get(key) for key in ("ok", "data", "error")}
