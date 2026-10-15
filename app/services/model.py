import logging
import asyncio
import json
from time import perf_counter
from typing import AsyncIterator

import httpx

from app.config import CFG


logger = logging.getLogger(__name__)
small_semaphore = asyncio.Semaphore(CFG.small_task_semaphore)


class ModelError(Exception):
    """Raised when Ollama returns an invalid or unsuccessful response."""


def configuration_status() -> str:
    if CFG.llm_mode.lower() == "api":
        return "ok" if CFG.qwen_base_url and CFG.qwen_api_key else "degraded"
    return "ok" if CFG.ollama_base_url and CFG.main_model else "degraded"


async def health_status() -> str:
    """Probe the configured model endpoint without invoking a generation request."""
    if configuration_status() != "ok":
        return "degraded"
    if CFG.llm_mode.lower() == "api":
        url = f"{CFG.qwen_base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {CFG.qwen_api_key}"}
    else:
        url = f"{CFG.ollama_base_url.rstrip('/')}/api/tags"
        headers = {}
    try:
        timeout = min(CFG.model_timeout_sec, 5)
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
        return "ok"
    except Exception:
        logger.warning("model health probe failed", exc_info=True)
        return "degraded"


async def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.8,
    timeout: int = 30,
    enable_thinking: bool = False,
) -> str:
    return await _ollama_chat(
        messages,
        model=model or CFG.main_model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        enable_thinking=enable_thinking,
    )


async def small_chat(
    messages: list[dict[str, str]],
    max_tokens: int = 256,
    temperature: float = 0.0,
    enable_thinking: bool = False,
) -> str:
    async with small_semaphore:
        return await _ollama_chat(
            messages,
            model=CFG.small_model or CFG.main_model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=CFG.model_timeout_sec,
            enable_thinking=enable_thinking,
        )


async def stream_chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.8,
    timeout: int = 30,
    enable_thinking: bool = False,
) -> AsyncIterator[str]:
    """Yield response deltas from the configured model provider."""
    if CFG.llm_mode.lower() == "api":
        async for delta in _api_stream_chat(
            messages,
            model or CFG.main_model,
            max_tokens,
            temperature,
            timeout,
            enable_thinking,
        ):
            yield delta
        return

    async for delta in _ollama_stream_chat(
        messages,
        model=model or CFG.main_model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    ):
        yield delta


async def _ollama_chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    enable_thinking: bool,
) -> str:
    if CFG.llm_mode.lower() == "api":
        return await _api_chat(messages, model, max_tokens, temperature, timeout, enable_thinking)
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{CFG.ollama_base_url.rstrip('/')}/api/chat", json=payload)
            response.raise_for_status()
            result = response.json()
    except httpx.TimeoutException:
        raise
    except httpx.HTTPError as exc:
        raise ModelError("Ollama request failed") from exc
    except Exception as exc:
        raise ModelError("Ollama response was invalid") from exc
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        logger.info("Ollama model=%s elapsed_ms=%.1f", model, elapsed_ms)

    try:
        content = result["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise ModelError("Ollama response did not contain message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ModelError("Ollama response content was empty")
    return content


async def _ollama_stream_chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
) -> AsyncIterator[str]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", f"{CFG.ollama_base_url.rstrip('/')}/api/chat", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        delta = item.get("message", {}).get("content", "")
                    except (TypeError, ValueError) as exc:
                        raise ModelError("Ollama stream response was invalid") from exc
                    if delta:
                        yield delta
    except httpx.TimeoutException:
        raise
    except httpx.HTTPError as exc:
        raise ModelError("Ollama streaming request failed") from exc
    except ModelError:
        raise
    except Exception as exc:
        raise ModelError("Ollama streaming response was invalid") from exc
    finally:
        logger.info("Ollama stream model=%s elapsed_ms=%.1f", model, (perf_counter() - started) * 1000)


async def _api_chat(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    enable_thinking: bool,
) -> str:
    if not CFG.qwen_api_key:
        raise ModelError("API mode requires MY_DASHSCOPE_API_KEY")
    started = perf_counter()
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "enable_thinking": enable_thinking,
    }
    headers = {"Authorization": f"Bearer {CFG.qwen_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.post(f"{CFG.qwen_base_url.rstrip('/')}/chat/completions", json=payload)
            response.raise_for_status()
            result = response.json()
    except httpx.TimeoutException:
        raise
    except httpx.HTTPError as exc:
        raise ModelError("API model request failed") from exc
    finally:
        logger.info("API model=%s elapsed_ms=%.1f", model, (perf_counter() - started) * 1000)
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelError("API response did not contain choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ModelError("API response content was empty")
    return content


async def _api_stream_chat(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: int,
    enable_thinking: bool,
) -> AsyncIterator[str]:
    if not CFG.qwen_api_key:
        raise ModelError("API mode requires MY_DASHSCOPE_API_KEY")
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "enable_thinking": enable_thinking,
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {CFG.qwen_api_key}"}
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            async with client.stream(
                "POST",
                f"{CFG.qwen_base_url.rstrip('/')}/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        item = json.loads(data)
                        delta = item["choices"][0].get("delta", {}).get("content") or ""
                    except (KeyError, IndexError, TypeError, ValueError) as exc:
                        raise ModelError("API stream response was invalid") from exc
                    if delta:
                        yield delta
    except httpx.TimeoutException:
        raise
    except httpx.HTTPError as exc:
        raise ModelError("API streaming request failed") from exc
    except ModelError:
        raise
    except Exception as exc:
        raise ModelError("API streaming response was invalid") from exc
    finally:
        logger.info("API stream model=%s elapsed_ms=%.1f", model, (perf_counter() - started) * 1000)
