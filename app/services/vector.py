import asyncio
import logging
from collections import OrderedDict

from app.config import CFG
from app.services import embedding


logger = logging.getLogger(__name__)
retry_queue = asyncio.Queue(maxsize=CFG.vector_retry_queue_max)
note_retry_queue = asyncio.Queue(maxsize=CFG.vector_retry_queue_max)
_events: OrderedDict[str, dict] = OrderedDict()
_notes: OrderedDict[str, dict] = OrderedDict()
_milvus = None
_milvus_ready = False
COLLECTION_NAME = "memory_events"
NOTE_COLLECTION_NAME = "memory_notes"


def health_status() -> str:
    return "ok" if _milvus_ready else "degraded"


async def init_collections() -> None:
    global _milvus, _milvus_ready
    try:
        from pymilvus import MilvusClient

        kwargs = {"uri": CFG.milvus_uri, "token": CFG.milvus_token} if CFG.milvus_token else {"uri": CFG.milvus_uri}
        _milvus = MilvusClient(**kwargs, db_name=CFG.milvus_db)
        for collection_name in (COLLECTION_NAME, NOTE_COLLECTION_NAME):
            if not _milvus.has_collection(collection_name):
                _milvus.create_collection(
                    collection_name=collection_name,
                    dimension=CFG.embedding_dim,
                    primary_field_name="id",
                    id_type="int",
                    vector_field_name="vector",
                    metric_type="COSINE",
                    auto_id=False,
                )
        _milvus_ready = True
    except Exception:
        _milvus_ready = False
        logger.info("Milvus unavailable; using in-memory vector backend", exc_info=True)


async def add_event(event_id, text: str, importance: str = "mid", user_id: int = 1) -> None:
    if str(event_id) in _events and not _events[str(event_id)].get("deleted"):
        return
    if _milvus_ready:
        vector = await embedding.embed(text)
        await asyncio.to_thread(
            _milvus_upsert,
            COLLECTION_NAME,
            {"id": int(event_id), "vector": vector, "text": text, "importance": importance, "user_id": user_id},
        )
    _events[str(event_id)] = {"text": text, "importance": importance, "user_id": user_id, "deleted": False}


async def safe_add_event(event_id, text: str, importance: str = "mid", user_id: int = 1) -> None:
    try:
        await add_event(event_id, text, importance, user_id)
    except Exception:
        try:
            retry_queue.put_nowait((event_id, text, importance, user_id))
        except asyncio.QueueFull:
            logger.warning("Milvus retry queue full; dropping event_id=%s", event_id)


async def add_note(note_id, text: str, importance: str = "mid", user_id: int = 1) -> None:
    if str(note_id) in _notes and not _notes[str(note_id)].get("deleted"):
        return
    if _milvus_ready:
        vector = await embedding.embed(text)
        await asyncio.to_thread(
            _milvus_upsert,
            NOTE_COLLECTION_NAME,
            {
                "id": int(note_id),
                "vector": vector,
                "text": text,
                "importance": importance,
                "user_id": user_id,
            },
        )
    _notes[str(note_id)] = {"text": text, "importance": importance, "user_id": user_id, "deleted": False}


async def safe_add_note(note_id, text: str, importance: str = "mid", user_id: int = 1) -> None:
    try:
        await add_note(note_id, text, importance, user_id)
    except Exception:
        try:
            note_retry_queue.put_nowait((note_id, text, importance, user_id))
        except asyncio.QueueFull:
            logger.warning("Milvus note retry queue full; dropping note_id=%s", note_id)


async def search(query: str, k: int = 3, min_score: float = 0.65, user_id: int = 1) -> list[dict]:
    if _milvus_ready:
        try:
            vector = await embedding.embed(query)
            rows = await asyncio.to_thread(_search_milvus, vector, k, user_id)
            return [
                {
                    "id": str(row["id"]),
                    "text": row["entity"]["text"],
                    "similarity": row["distance"],
                    "importance": row["entity"].get("importance", "mid"),
                }
                for row in rows[0]
                if row["distance"] >= min_score
            ]
        except Exception:
            logger.warning("Milvus semantic search unavailable; using lexical fallback", exc_info=True)
    query_terms = set(query.lower().split())
    results = []
    for event_id, item in _events.items():
        if item.get("deleted") or item.get("user_id") != user_id:
            continue
        terms = set(item["text"].lower().split())
        score = len(query_terms & terms) / max(len(query_terms | terms), 1)
        if score >= min_score:
            results.append({"id": event_id, "text": item["text"], "similarity": score, "importance": item["importance"]})
    return sorted(results, key=lambda item: item["similarity"], reverse=True)[:k]


def _search_milvus(vector: list[float], k: int, user_id: int):
    return _milvus.search(
        collection_name=COLLECTION_NAME,
        data=[vector],
        limit=k,
        output_fields=["text", "importance", "user_id"],
        filter=f"user_id == {user_id}",
    )


def _milvus_upsert(collection_name: str, row: dict) -> None:
    write = getattr(_milvus, "upsert", _milvus.insert)
    write(collection_name=collection_name, data=[row])


def _search_milvus_notes(vector: list[float], k: int, user_id: int):
    return _milvus.search(
        collection_name=NOTE_COLLECTION_NAME,
        data=[vector],
        limit=k,
        output_fields=["text", "importance", "user_id"],
        filter=f"user_id == {user_id}",
    )


def _delete_milvus_event(vector_id) -> None:
    _milvus.delete(collection_name=COLLECTION_NAME, filter=f"id == {int(vector_id)}")


async def search_notes(query: str, k: int = 3, min_score: float = 0.0, user_id: int = 1) -> list[dict]:
    if _milvus_ready:
        try:
            vector = await embedding.embed(query)
            rows = await asyncio.to_thread(_search_milvus_notes, vector, k, user_id)
            return [
                {
                    "id": str(row["id"]),
                    "text": row["entity"]["text"],
                    "similarity": row["distance"],
                    "importance": row["entity"].get("importance", "mid"),
                }
                for row in rows[0]
                if row["distance"] >= min_score
            ]
        except Exception:
            logger.warning("Milvus note search unavailable; using lexical fallback", exc_info=True)
    query_terms = set(query.lower().split())
    results = []
    for note_id, item in _notes.items():
        if item.get("deleted") or item.get("user_id") != user_id:
            continue
        terms = set(item["text"].lower().split())
        score = len(query_terms & terms) / max(len(query_terms | terms), 1)
        if score >= min_score:
            results.append(
                {
                    "id": note_id,
                    "text": item["text"],
                    "similarity": score,
                    "importance": item["importance"],
                }
            )
    return sorted(results, key=lambda item: item["similarity"], reverse=True)[:k]


async def delete_event(vector_id) -> bool:
    try:
        if _milvus_ready:
            await asyncio.to_thread(_delete_milvus_event, vector_id)
        _events.pop(str(vector_id), None)
        return True
    except Exception:
        logger.warning("Milvus event deletion failed vector_id=%s", vector_id, exc_info=True)
        return False


async def retry_pending() -> None:
    while not retry_queue.empty():
        event_id, text, importance, user_id = await retry_queue.get()
        try:
            await add_event(event_id, text, importance, user_id)
        finally:
            retry_queue.task_done()
    while not note_retry_queue.empty():
        note_id, text, importance, user_id = await note_retry_queue.get()
        try:
            await add_note(note_id, text, importance, user_id)
        finally:
            note_retry_queue.task_done()
