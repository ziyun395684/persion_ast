import asyncio
import logging
from typing import Any

from app.config import CFG


logger = logging.getLogger(__name__)
_client: Any = None


def _bank_id(user_id: int | None = None) -> str:
    return f"user-{user_id}" if user_id is not None else CFG.hindsight_bank_id


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from hindsight_client import Hindsight
    except Exception as exc:
        raise RuntimeError("hindsight-client is not installed") from exc
    _client = Hindsight(
        base_url=CFG.hindsight_url,
        api_key=CFG.hindsight_api_key,
        timeout=CFG.hindsight_timeout_sec,
    )
    return _client


def _run_sync(method_name: str, **kwargs):
    client = _get_client()
    method = getattr(client, method_name)
    return method(**kwargs)


async def _run_async(method_name: str, **kwargs):
    client = _get_client()
    async_method_names = {
        "get": "aget_mental_model",
        "get_mental_model_content": "aget_mental_model",
    }
    async_method = getattr(
        client,
        async_method_names.get(method_name, f"a{method_name}"),
        None,
    )
    if async_method is not None:
        return await async_method(**kwargs)
    return await asyncio.to_thread(_run_sync, method_name, **kwargs)


async def close() -> None:
    global _client
    client = _client
    _client = None
    if client is None:
        return
    try:
        async_close = getattr(client, "aclose", None)
        if async_close is not None:
            await async_close()
        else:
            await asyncio.to_thread(client.close)
    except Exception:
        logger.warning("hindsight client close failed", exc_info=True)


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "answer", "result"):
            if isinstance(value.get(key), str):
                return value[key]
    for key in ("text", "content", "answer", "result"):
        item = getattr(value, key, None)
        if isinstance(item, str):
            return item
    return str(value) if value is not None else ""


async def retain(
    content: str,
    context: str | None = None,
    tags: list[str] | None = None,
    document_id: str | None = None,
    metadata: dict[str, str] | None = None,
    user_id: int | None = None,
) -> bool:
    if not CFG.hindsight_enabled:
        return False
    try:
        await asyncio.wait_for(
            _run_async(
                "retain",
                bank_id=_bank_id(user_id),
                content=content,
                context=context,
                **({"document_id": document_id} if document_id else {}),
                metadata=metadata,
                tags=tags or [],
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
        return True
    except Exception:
        logger.warning("hindsight retain failed", exc_info=True)
        return False


async def delete_knowledge_node(node_id: str, user_id: int | None = None) -> bool:
    """Best-effort deletion for a known Hindsight knowledge node."""
    if not CFG.hindsight_enabled:
        return False
    try:
        await asyncio.wait_for(
            _run_async(
                "delete_knowledge_node",
                bank_id=_bank_id(user_id),
                node_id=node_id,
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
        return True
    except Exception:
        logger.warning("hindsight knowledge node deletion failed node_id=%s", node_id, exc_info=True)
        return False
async def recall(query: str, budget: str = "mid", user_id: int | None = None) -> list[dict]:
    if not CFG.hindsight_enabled:
        return []
    try:
        result = await asyncio.wait_for(
            _run_async(
                "recall",
                bank_id=_bank_id(user_id),
                query=query,
                budget=budget,
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
    except Exception:
        logger.warning("hindsight recall failed", exc_info=True)
        return []
    if isinstance(result, dict):
        items = result.get("results", [])
    else:
        items = getattr(result, "results", result)
    if not isinstance(items, list):
        return []
    normalized = []
    for item in items:
        if isinstance(item, dict):
            text = _text_value(item)
            if text:
                normalized.append({"text": text, "type": item.get("type", "unknown")})
        elif _text_value(item):
            normalized.append({"text": _text_value(item), "type": getattr(item, "type", "unknown")})
    return normalized


async def reflect(query: str, user_id: int | None = None) -> str:
    if not CFG.hindsight_enabled:
        return ""
    try:
        result = await asyncio.wait_for(
            _run_async(
                "reflect",
                bank_id=_bank_id(user_id),
                query=query,
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
        return _text_value(result)
    except Exception:
        logger.warning("hindsight reflect failed", exc_info=True)
        return ""


async def get_mental_model(model_id: str) -> str:
    if not CFG.hindsight_enabled:
        return ""
    return await get_mental_model_content(model_id)


async def create_mental_model(model_id: str, name: str, source_query: str, user_id: int | None = None) -> bool:
    if not CFG.hindsight_enabled:
        return False
    try:
        client = _get_client()
        method_name = "create_mental_model" if hasattr(client, "create_mental_model") else "create"
        kwargs = {
            "bank_id": _bank_id(user_id),
            "name": name,
            "source_query": source_query,
        }
        kwargs["id"] = model_id
        await asyncio.wait_for(
            _run_async(
                method_name,
                **kwargs,
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
        return True
    except Exception:
        logger.warning("hindsight mental model creation failed id=%s", model_id, exc_info=True)
        return False


async def list_mental_models(user_id: int | None = None) -> list:
    if not CFG.hindsight_enabled:
        return []
    try:
        client = _get_client()
        method_name = "list_mental_models" if hasattr(client, "list_mental_models") else "list"
        result = await asyncio.wait_for(
            _run_async(
                method_name,
                bank_id=_bank_id(user_id),
                **({"detail": "metadata"} if method_name == "list" else {}),
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
    except Exception:
        logger.warning("hindsight mental model listing failed", exc_info=True)
        return []
    if isinstance(result, dict):
        result = result.get("models", result.get("items", []))
    elif hasattr(result, "models"):
        result = result.models
    elif hasattr(result, "items"):
        result = result.items
    return result if isinstance(result, list) else []


async def get_mental_model_content(model_id: str, user_id: int | None = None) -> str:
    if not CFG.hindsight_enabled:
        return ""
    try:
        client = _get_client()
        method_name = (
            "get_mental_model_content"
            if hasattr(client, "get_mental_model_content")
            else "get"
        )
        kwargs = {"bank_id": _bank_id(user_id)}
        kwargs["model_id" if method_name == "get_mental_model_content" else "mental_model_id"] = model_id
        if method_name == "get":
            kwargs["detail"] = "content"
        result = await asyncio.wait_for(
            _run_async(
                method_name,
                **kwargs,
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
        return _text_value(result)
    except Exception:
        logger.warning("hindsight mental model content read failed id=%s", model_id, exc_info=True)
        return ""


async def is_healthy() -> bool:
    if not CFG.hindsight_enabled:
        return False
    try:
        await asyncio.wait_for(
            _run_async(
                "recall",
                bank_id=CFG.hindsight_bank_id,
                query="ping",
                budget="low",
            ),
            timeout=CFG.hindsight_timeout_sec,
        )
        return True
    except Exception:
        logger.warning("hindsight health check failed", exc_info=True)
        return False
