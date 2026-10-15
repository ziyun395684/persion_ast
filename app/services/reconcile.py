import logging

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session
from typing import TypedDict

from app import db
from app.models import MemoryEvent
from app.services import vector


logger = logging.getLogger(__name__)


class ReconcileState(TypedDict, total=False):
    cleaned: int
    repaired: int
    failed: int


def _open_session() -> Session:
    return db.SessionLocal()


async def reconcile_node(_: ReconcileState) -> dict:
    await vector.init_collections()
    cleaned = repaired = failed = 0
    with _open_session() as session:
        events = session.query(MemoryEvent).all()
        sql_ids = {str(event.id) for event in events}
        for vector_id in list(vector._events):
            if vector_id not in sql_ids:
                await vector.delete_event(vector_id)
                cleaned += 1
        vector_ids = set(vector._events)
        for event in events:
            if str(event.id) in vector_ids:
                continue
            try:
                await vector.safe_add_event(event.id, event.event_text, event.importance, event.user_id)
                repaired += 1
            except Exception:
                failed += 1
                logger.exception("vector reconciliation failed event_id=%s", event.id)
    return {"cleaned": cleaned, "repaired": repaired, "failed": failed}


def build_reconcile_graph():
    graph = StateGraph(ReconcileState)
    graph.add_node("reconcile", reconcile_node)
    graph.add_edge(START, "reconcile")
    graph.add_edge("reconcile", END)
    return graph.compile()


reconcile_graph = build_reconcile_graph()
