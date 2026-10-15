import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from app import db
from app.config import CFG
from app.services import model, vector
from app.services import hindsight
from app.services.vector import retry_queue


router = APIRouter()


def check_database() -> str:
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "degraded"


@router.get("/health")
async def health() -> dict[str, str | int]:
    db_status = check_database()
    if not CFG.hindsight_enabled:
        hindsight_status = "disabled"
    else:
        hindsight_status = "ok" if await hindsight.is_healthy() else "degraded"
    return {
        "db": db_status,
        "vector": vector.health_status(),
        "model": model.configuration_status(),
        "hindsight": hindsight_status,
        "workers": 1,
        "vector_retry_queue_size": retry_queue.qsize(),
    }


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> dict[str, str | int]:
    model_status, = await asyncio.gather(model.health_status())
    db_status = check_database()
    vector_status = vector.health_status()
    if not CFG.hindsight_enabled:
        hindsight_status = "disabled"
    else:
        hindsight_status = "ok" if await hindsight.is_healthy() else "degraded"
    required_ok = db_status == "ok" and model_status == "ok"
    all_services_ok = vector_status == "ok" and hindsight_status in {"ok", "disabled"}
    return {
        "status": "ready" if required_ok and all_services_ok else "degraded",
        "db": db_status,
        "model": model_status,
        "vector": vector_status,
        "hindsight": hindsight_status,
        "workers": 1,
        "vector_retry_queue_size": retry_queue.qsize(),
    }
