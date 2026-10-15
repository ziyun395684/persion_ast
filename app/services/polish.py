import json
import logging
import re

from app.config import CFG
from app.services import model


logger = logging.getLogger(__name__)


def _format_raw_result(raw_result) -> str:
    if isinstance(raw_result, str):
        return raw_result
    return json.dumps(raw_result, ensure_ascii=False, default=str)


def _limit_sentences(text: str) -> str:
    sentences = [item.strip() for item in re.split(r"(?<=[。！？!?])", text.strip()) if item.strip()]
    return "".join(sentences[:3]) if sentences else text.strip()


def _build_prompt(
    task_name: str,
    raw_result,
    also_chat: bool,
    recalled_events: list[dict] | None,
    l2_summary: str | None,
) -> str:
    prompt = f"""你是小玉。男朋友让你帮他【{task_name}】，工具返回结果是：
{_format_raw_result(raw_result)}
"""
    if also_chat:
        prompt += f"""
你们最近的相处上下文：
{l2_summary or "（无）"}
{json.dumps(recalled_events or [], ensure_ascii=False, default=str)}
"""
    prompt += """
请用你平时的语气把这个结果告诉他，像女朋友帮完忙顺手汇报一下那样。
要求：
- 不要复述 JSON、不要罗列字段名。
- 该提醒的关心一句（比如下雨记得带伞）。
- 若上下文显示他今天状态不好，先关心一句再汇报。
- 长度 ≤ 3 句。
"""
    return prompt


async def _polish_impl(
    task_name: str,
    raw_result,
    also_chat: bool,
    recalled_events: list[dict] | None,
    l2_summary: str | None,
) -> str:
    if isinstance(raw_result, dict) and raw_result.get("ok") is False:
        return "哎呀这个我没查到，等会儿再试试好不好"
    prompt = _build_prompt(task_name, raw_result, also_chat, recalled_events, l2_summary)
    try:
        result = await model.small_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=CFG.polish_model_max_tokens,
            temperature=CFG.temperature["polish"],
        )
    except Exception:
        logger.exception("tool result polishing failed")
        return "哎呀，我已经帮你处理啦，不过回复时卡了一下，等会儿再告诉你～"
    return _limit_sentences(result)


async def polish(
    task_name: str,
    raw_result,
    also_chat: bool,
    recalled_events: list[dict] | None,
    l2_summary: str | None,
) -> str:
    from app.services.graph import polish_graph

    result = await polish_graph.ainvoke(
        {
            "task_name": task_name,
            "raw_result": raw_result,
            "also_chat": also_chat,
            "recalled_events": recalled_events or [],
            "l2_summary": l2_summary,
        }
    )
    return result.get("reply", "")
