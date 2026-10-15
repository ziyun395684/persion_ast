import asyncio
import logging

from app import db
from app.config import CFG
from app.services import model
from app.services.graph import jobs_graph


logger = logging.getLogger(__name__)
semaphore = model.small_semaphore


async def extract_polling_job() -> None:
    delay = CFG.extract_polling_interval_sec
    while True:
        try:
            with db.SessionLocal() as session:
                result = await jobs_graph.ainvoke(
                    {"operation": "extract"}, context={"db": session}
                )
            processed = int(result.get("processed", 0))
            delay = CFG.extract_polling_interval_sec if processed else min(delay * 2, 60)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = min(delay * 2, 60)
            logger.warning("extract polling failed error=%s", type(exc).__name__)
        await asyncio.sleep(delay)


async def vector_retry_job() -> None:
    while True:
        try:
            await jobs_graph.ainvoke({"operation": "vector_retry"})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("vector retry failed")
        await asyncio.sleep(CFG.vector_retry_interval_sec)
