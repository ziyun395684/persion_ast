from __future__ import annotations

import httpx

from app.config import CFG


class EmbeddingError(RuntimeError):
    """Raised when the configured embedding provider returns an unusable vector."""


def _validate_vector(value) -> list[float]:
    if not isinstance(value, list) or not value or not all(isinstance(item, (int, float)) for item in value):
        raise EmbeddingError("embedding response did not contain a vector")
    vector = [float(item) for item in value]
    if len(vector) != CFG.embedding_dim:
        raise EmbeddingError(
            f"embedding dimension {len(vector)} does not match configured dimension {CFG.embedding_dim}"
        )
    return vector


def _extract_vector(payload: dict, provider: str) -> list[float]:
    if provider == "api":
        data = payload.get("data")
        if isinstance(data, list) and data:
            return _validate_vector(data[0].get("embedding"))
    else:
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            return _validate_vector(embeddings[0])
        if "embedding" in payload:
            return _validate_vector(payload["embedding"])
    raise EmbeddingError("embedding response did not contain a supported vector payload")


async def embed(text: str) -> list[float]:
    if not text or not text.strip():
        raise EmbeddingError("embedding input is empty")

    provider = "api" if CFG.llm_mode.lower() == "api" else "ollama"
    if provider == "api":
        url = f"{CFG.qwen_base_url.rstrip('/')}/embeddings"
        headers = {"Authorization": f"Bearer {CFG.qwen_api_key}"} if CFG.qwen_api_key else {}
    else:
        url = f"{CFG.ollama_base_url.rstrip('/')}/api/embed"
        headers = {}
    payload = {"model": CFG.embedding_model, "input": text}

    try:
        async with httpx.AsyncClient(
            timeout=CFG.model_timeout_sec,
            headers=headers,
        ) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return _extract_vector(response.json(), provider)
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError("embedding provider request failed") from exc
