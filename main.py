from contextlib import asynccontextmanager
import asyncio
import logging
from time import perf_counter
from uuid import uuid4
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.auth import router as auth_router
from app.api.assistant import router as assistant_router
from app.api.health import router as health_router
from app.api.persona import router as persona_router
from app.api.conversation import router as conversation_router
from app.api.memory import router as memory_router
from app.api.voice import router as voice_router
from app.config import CFG
from app import db
from app.services import hindsight
from app.services import intent
from app.services import vector


logging.getLogger("app").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.getLogger("app").setLevel(logging.INFO)
    db.init_db()
    await vector.init_collections()
    if CFG.laya_enabled:
        await asyncio.to_thread(intent.preload_laya)
    from app.services import jobs

    tasks = [
        asyncio.create_task(jobs.extract_polling_job()),
        asyncio.create_task(jobs.vector_retry_job()),
    ]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await hindsight.close()


app = FastAPI(debug=CFG.debug, lifespan=lifespan)


@app.middleware("http")
async def request_observability(request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    started = perf_counter()
    response = await call_next(request)
    elapsed_ms = (perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("app.http").info(
        "http_request request_id=%s method=%s path=%s status=%s elapsed_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(assistant_router)
app.include_router(persona_router)
app.include_router(conversation_router)
app.include_router(memory_router)
app.include_router(voice_router)
if CFG.debug:
    from app.api.memory import debug_router as memory_debug_router

    app.include_router(memory_debug_router)

app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "frontend", html=True),
    name="frontend",
)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host=CFG.host, port=CFG.port)
