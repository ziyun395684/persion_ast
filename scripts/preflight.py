"""Check deployment prerequisites without printing credentials."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.config import CFG
from app.services import hindsight


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def check_database() -> Check:
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return Check("database", True, "SELECT 1")
    except Exception as exc:
        return Check("database", False, type(exc).__name__)


def check_model() -> Check:
    if CFG.llm_mode.lower() == "api":
        if not CFG.qwen_base_url or not CFG.qwen_api_key or not CFG.main_model:
            return Check("model", False, "API configuration incomplete")
        url = f"{CFG.qwen_base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {CFG.qwen_api_key}"}
    else:
        if not CFG.ollama_base_url or not CFG.main_model:
            return Check("model", False, "Ollama configuration incomplete")
        url = f"{CFG.ollama_base_url.rstrip('/')}/api/tags"
        headers = {}
    try:
        response = httpx.get(url, headers=headers, timeout=CFG.model_timeout_sec)
        response.raise_for_status()
        return Check("model", True, f"{CFG.llm_mode}:{CFG.main_model}")
    except Exception as exc:
        return Check("model", False, type(exc).__name__)


def check_milvus() -> Check:
    try:
        from pymilvus import MilvusClient

        kwargs = {"uri": CFG.milvus_uri}
        if CFG.milvus_token:
            kwargs["token"] = CFG.milvus_token
        client = MilvusClient(**kwargs, db_name=CFG.milvus_db)
        client.list_collections()
        return Check("milvus", True, CFG.milvus_uri, required=False)
    except Exception as exc:
        return Check("milvus", False, type(exc).__name__, required=False)


async def check_hindsight() -> Check:
    if not CFG.hindsight_enabled:
        return Check("hindsight", True, "disabled", required=False)
    try:
        healthy = await hindsight.is_healthy()
        return Check("hindsight", healthy, "reachable" if healthy else "degraded", required=False)
    finally:
        await hindsight.close()


async def run() -> list[Check]:
    checks = [check_database(), check_model(), check_milvus()]
    checks.append(await check_hindsight())
    return checks


def main() -> int:
    checks = asyncio.run(run())
    for check in checks:
        print(f"{check.name}: {'ok' if check.ok else 'failed'} ({check.detail})")
    return 0 if all(check.ok or not check.required for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
