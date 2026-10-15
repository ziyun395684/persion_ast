import json
import logging
import asyncio
import time
from typing import Any

from app.config import CFG
from app.prompts.persona import STYLE_PRESET_TEXT
from app.services import model


logger = logging.getLogger(__name__)

_laya_agent: Any = None
_laya_unavailable_until = 0.0
LAYA_FAILURE_COOLDOWN_SEC = 300.0

INTENT_PROMPT = """你是单用户 AI 女友兼助手的意图分类器。
请只输出一个 JSON 对象，不要输出 Markdown、解释或额外文字。

允许的 intent：chat、task、style_switch、forget。
允许的 task_type：todo、weather、calendar、note、search、time、none。

字段要求：
- intent：只能是允许的四个值之一
- task_type：只能是允许的六个值之一
- also_chat：必须是 true 或 false
- reasoning：一句简短中文原因
- style_preset：当 intent=style_switch 时，只能是 soft_milk、genki_bounce、gentle_warm 之一
- tool_args：当 intent=task 时，填写工具调用所需的 JSON 参数

规则：
- 纯聊天或情绪表达：intent=chat，task_type=none
- 需要执行助手任务：intent=task
- 同时表达情感和任务：intent=task，also_chat=true
- 修改说话风格：intent=style_switch，task_type=none
- 忘记某条记忆：intent=forget，task_type=none

用户消息：
{user_msg}
"""

VALID_INTENTS = {"chat", "task", "style_switch", "forget"}
VALID_TASK_TYPES = {"todo", "weather", "calendar", "note", "search", "time", "none"}
VALID_STYLE_PRESETS = set(STYLE_PRESET_TEXT)

STYLE_KEYWORDS = {
    "soft_milk": ("软萌", "可爱一点", "撒娇一点", "奶糖", "萌一点"),
    "genki_bounce": ("元气", "活泼一点", "开心一点", "逗一点", "有活力"),
    "gentle_warm": ("温柔", "温和一点", "轻柔一点", "柔和一点", "多陪陪我"),
}

LAYA_QUESTIONS = {
    "intent": {
        "type": "choice",
        "instructions": "判断用户消息的主意图。只能选择一个。",
        "criteria": {value: None for value in sorted(VALID_INTENTS)},
    },
    "task_type": {
        "type": "choice",
        "instructions": "如果是任务，判断任务类型；否则选择 none。",
        "criteria": {value: None for value in sorted(VALID_TASK_TYPES)},
    },
    "also_chat": {
        "type": "noul",
        "instructions": "用户是否同时表达了情感或希望陪伴聊天？",
    },
}


def _fallback() -> dict:
    return {
        "intent": "chat",
        "task_type": "none",
        "also_chat": True,
        "reasoning": "分类结果无效，按普通聊天处理",
    }


def _extract_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value if isinstance(value, dict) else None
    return None


def _normalize(value: dict | None, raw: str) -> dict:
    if value is None:
        return _fallback()
    intent = value.get("intent")
    task_type = value.get("task_type")
    also_chat = value.get("also_chat")
    reasoning = value.get("reasoning", "")
    if (
        intent not in VALID_INTENTS
        or task_type not in VALID_TASK_TYPES
        or not isinstance(also_chat, bool)
        or not isinstance(reasoning, str)
    ):
        logger.warning("invalid intent classification output: %s", raw)
        return _fallback()
    if intent == "forget" and task_type != "none":
        logger.warning("forget intent overrides task_type=%s", task_type)
        task_type = "none"
    result = {
        "intent": intent,
        "task_type": task_type,
        "also_chat": also_chat,
        "reasoning": reasoning,
    }
    style_preset = value.get("style_preset")
    if style_preset in VALID_STYLE_PRESETS:
        result["style_preset"] = style_preset
    tool_args = value.get("tool_args")
    if isinstance(tool_args, dict):
        result["tool_args"] = tool_args
    return result


def _load_laya_agent() -> Any:
    global _laya_agent
    import laya

    if _laya_agent is None:
        _laya_agent = laya.load(CFG.laya_model, device=CFG.laya_device)
    return _laya_agent


def preload_laya() -> bool:
    """Load the configured Laya checkpoint before the first chat request."""
    if not CFG.laya_enabled:
        return False
    try:
        _load_laya_agent()
        return True
    except Exception:
        logger.exception("Laya preload failed; intent classification will use fallback")
        return False


def _classify_with_laya(user_msg: str) -> dict | None:
    """Run Laya's fixed-choice classifier; return None when it abstains or is unavailable."""
    global _laya_agent, _laya_unavailable_until
    try:
        import laya

        laya_agent = _load_laya_agent()
        details = laya.decide(
            laya_agent,
            user_msg,
            questions=LAYA_QUESTIONS,
            return_details=True,
            min_confidence=CFG.laya_min_confidence,
        )
        values = getattr(details, "values", None)
        if not isinstance(values, dict):
            return None
        confidences = getattr(details, "answer_confidence", {}) or {}
        required = ("intent", "task_type", "also_chat")
        if any(
            not isinstance(confidences.get(field), (int, float))
            or confidences[field] < CFG.laya_min_confidence
            for field in required
        ):
            return None
        normalized = _normalize(
            {
                **values,
                "reasoning": "Laya 高置信度分类",
            },
            repr(details),
        )
        _laya_unavailable_until = 0.0
        return normalized if normalized["reasoning"] == "Laya 高置信度分类" else None
    except Exception:
        _laya_unavailable_until = time.monotonic() + LAYA_FAILURE_COOLDOWN_SEC
        logger.exception("Laya intent classification failed; falling back to small model")
        return None


async def classify(user_msg: str) -> dict:
    if CFG.laya_enabled and time.monotonic() >= _laya_unavailable_until:
        laya_result = await asyncio.to_thread(_classify_with_laya, user_msg)
        if laya_result is not None:
            return laya_result
    prompt = INTENT_PROMPT.format(user_msg=user_msg)
    try:
        raw = await model.small_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=CFG.intent_max_output_tokens,
            temperature=CFG.temperature["classify"],
        )
    except Exception:
        logger.exception("intent classification failed")
        return _fallback()
    return _normalize(_extract_json(raw), raw)


def _keyword_style_switch(user_msg: str) -> str | None:
    text = (user_msg or "").strip().lower()
    for style_preset, keywords in STYLE_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in keywords):
            return style_preset
    return None


def _resolve_style_switch(user_msg: str, classification: dict) -> str | None:
    keyword_style = _keyword_style_switch(user_msg)
    if keyword_style is not None:
        return keyword_style
    if classification.get("intent") != "style_switch":
        return None
    style_preset = classification.get("style_preset")
    return style_preset if style_preset in VALID_STYLE_PRESETS else None


async def detect_style_switch(
    user_msg: str, classification: dict | None = None
) -> str | None:
    """Resolve an explicit style request, with classifier confirmation as fallback."""
    result = classification if classification is not None else await classify(user_msg)
    return _resolve_style_switch(user_msg, result)
