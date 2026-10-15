import logging

from sqlalchemy.orm import Session

from app.config import CFG
from app.models import MemoryEvent
from app.services import vector


logger = logging.getLogger(__name__)

FORGET_HIT_REPLY = "好哒，那件事我不提了～"
FORGET_MISS_REPLY = "哥哥说的是哪件事呀？我有点记不清了"


async def _forget_impl(db: Session, user_msg: str, user_id: int = 1) -> str:
    try:
        matches = await vector.search(
            user_msg,
            k=1,
            min_score=CFG.forget_min_score,
            user_id=user_id,
        )
    except TypeError as exc:
        if "user_id" not in str(exc):
            raise
        matches = await vector.search(user_msg, k=1, min_score=CFG.forget_min_score)
    match = matches[0] if matches else None
    event_id = match.get("id") if match else None
    score = match.get("similarity") if match else None
    logger.info("forget query=%s event_id=%s score=%s", user_msg, event_id, score)
    if match is None:
        return FORGET_MISS_REPLY
    try:
        event = db.get(MemoryEvent, int(match["id"]))
    except (TypeError, ValueError):
        event = None
    if event is None or event.deleted or event.user_id != user_id:
        return FORGET_MISS_REPLY

    event.deleted = 1
    try:
        db.commit()
        await vector.delete_event(event.id)
    except Exception:
        db.rollback()
        logger.exception("forget delete failed event_id=%s", event.id)
        return FORGET_MISS_REPLY
    return FORGET_HIT_REPLY


async def forget(db: Session, user_msg: str, user_id: int = 1) -> str:
    from app.services.graph import forget_graph

    result = await forget_graph.ainvoke(
        {"user_msg": user_msg}, context={"db": db, "user_id": user_id}
    )
    return result.get("reply", FORGET_MISS_REPLY)
