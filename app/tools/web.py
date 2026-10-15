import logging
from urllib.parse import urlparse

import httpx

from app.config import CFG


logger = logging.getLogger(__name__)


def _ascii_header_value(value: str) -> str:
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
    normalized = value.translate(str.maketrans(replacements))
    return normalized.encode("ascii").decode("ascii")


def _failure(answer: str = "联网查询暂时不可用，请稍后再试") -> dict:
    return {"ok": False, "answer": answer}


def _answer_from_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("answer", "result", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        nested = _answer_from_payload(data)
        if nested:
            return nested
    result = payload.get("Result")
    if isinstance(result, dict):
        web_results = result.get("WebResults")
        if isinstance(web_results, list):
            lines = []
            for item in web_results:
                if not isinstance(item, dict):
                    continue
                title = item.get("Title")
                summary = item.get("Summary") or item.get("Content") or item.get("Snippet")
                if isinstance(summary, str) and summary.strip():
                    prefix = f"{title}: " if isinstance(title, str) and title.strip() else ""
                    lines.append(f"{prefix}{summary.strip()}")
            if lines:
                return "\n".join(lines)
    results = payload.get("results")
    if isinstance(results, list):
        lines = []
        for item in results:
            if not isinstance(item, dict):
                continue
            text = item.get("content") or item.get("snippet") or item.get("title")
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
        if lines:
            return "\n".join(lines)
    return None


async def _web_query_impl(query: str) -> dict:
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        return {"ok": False, "answer": "查询内容不能为空"}
    logger.info("web query=%s", query)
    if not CFG.web_query_api_key:
        return _failure("联网查询未配置 API Key")
    if not CFG.web_query_endpoint:
        return _failure("联网查询未配置接口地址")

    headers = {
        "Authorization": f"Bearer {CFG.web_query_api_key}",
        "Content-Type": "application/json",
    }
    if CFG.web_query_api_version:
        try:
            headers["X-API-Version"] = _ascii_header_value(CFG.web_query_api_version)
        except UnicodeError:
            return _failure("联网查询接口版本配置无效")
    try:
        endpoint_host = (urlparse(CFG.web_query_endpoint).hostname or "").lower()
        if endpoint_host == "open.feedcoopapi.com":
            payload = {
                "Query": query,
                "SearchType": "web",
                "Count": 5,
                "Filter": {"NeedContent": True, "NeedUrl": True},
                "NeedSummary": True,
            }
        else:
            payload = {"query": query}
        async with httpx.AsyncClient(timeout=CFG.web_query_timeout) as client:
            response = await client.post(
                CFG.web_query_endpoint,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            answer = _answer_from_payload(response.json())
    except httpx.TimeoutException:
        logger.warning("web query timed out query=%s", query)
        return _failure("联网查询超时了，请稍后再试")
    except httpx.HTTPError:
        logger.exception("web query request failed query=%s", query)
        return _failure()
    except Exception:
        logger.exception("web query response invalid query=%s", query)
        return _failure()
    if not answer:
        return _failure("没有查到相关结果")
    return {"ok": True, "answer": answer}


async def web_query(query: str) -> dict:
    from app.services.graph import web_graph

    result = await web_graph.ainvoke({"query": query})
    return {"ok": result.get("ok", False), "answer": result.get("answer", "")}
