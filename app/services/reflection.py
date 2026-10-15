import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import desc, select, update, func
from sqlalchemy.orm import Session

from app.config import CFG
from app.models import ChatMessage, MemoryProfile
from app.services import model
from app.services.memory import estimate_tokens


logger = logging.getLogger(__name__)

REFLECTION_PROMPT = """你在帮 AI 女友总结最近的相处模式，只提炼行为倾向，不要复述聊天记录。
请严格输出 JSON：
{{
  "user_triggers": [{{"text": "用户在什么情境下需要什么"}}],
  "her_habits": [{{"text": "她应该采取什么陪伴方式"}}],
  "tone_adjustment": "一句话语气调整建议",
  "hit_items": [0, 2]
}}

当前快照：
{snapshot}

最近对话：
{dialogue}

隐式反馈信号：
{signals}

hit_items 只能填写当前快照 items 中实际被本轮对话使用的条目下标。
"""


def _today() -> date:
    return datetime.now().astimezone().date()


def _load_snapshot(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    items = value.get("items", []) if isinstance(value, dict) else []
    if not isinstance(items, list):
        return []
    normalized = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        normalized.append(
            {
                "text": item["text"],
                "created_at": item.get("created_at") or _today().isoformat(),
                "last_hit_at": item.get("last_hit_at"),
                "weight": _safe_weight(item.get("weight", 1.0)),
            }
        )
    return normalized


def _safe_weight(value) -> float:
    try:
        return min(max(float(value), 0.0), CFG.snapshot_weight_max)
    except (TypeError, ValueError):
        return 1.0


def _parse_result(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _valid_hit_items(value, item_count: int) -> list[int]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            item
            for item in value
            if isinstance(item, int) and not isinstance(item, bool) and 0 <= item < item_count
        }
    )


def _parse_day(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _implicit_signals(messages: list[ChatMessage]) -> str:
    user_messages = [item for item in messages if item.role == "user"]
    assistant_messages = [item for item in messages if item.role == "assistant"]
    user_lengths = [len(item.content) for item in user_messages]
    assistant_lengths = [len(item.content) for item in assistant_messages]
    negative_words = ("累", "烦", "难受", "焦虑", "不开心", "讨厌", "压力")
    negative_count = sum(
        any(word in item.content for word in negative_words) for item in user_messages
    )
    continued_topics = sum(
        1
        for index in range(1, len(user_messages))
        if user_messages[index].content[:8] == user_messages[index - 1].content[:8]
    )
    return json.dumps(
        {
            "user_reply_lengths": user_lengths,
            "assistant_reply_lengths": assistant_lengths,
            "negative_signal_count": negative_count,
            "continued_topic_signal": continued_topics,
        },
        ensure_ascii=False,
    )


def _new_texts(result: dict) -> list[str]:
    texts = []
    for key in ("user_triggers", "her_habits"):
        values = result.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            text = item.get("text") if isinstance(item, dict) else item
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    tone = result.get("tone_adjustment")
    if isinstance(tone, str) and tone.strip():
        texts.append(tone.strip())
    return texts


def _merge_items(items: list[dict], result: dict, now: date) -> list[dict]:
    hits = _valid_hit_items(result.get("hit_items"), len(items))
    hit_set = set(hits)
    for index, item in enumerate(items):
        last_hit = _parse_day(item.get("last_hit_at"))
        stale = last_hit is not None and now - last_hit > timedelta(days=CFG.snapshot_decay_days)
        if index in hit_set:
            item["weight"] = min(
                item["weight"] + CFG.snapshot_hit_boost,
                CFG.snapshot_weight_max,
            )
            item["last_hit_at"] = now.isoformat()
        if stale:
            item["weight"] *= CFG.snapshot_decay_factor

    existing = {item["text"] for item in items}
    for text in _new_texts(result):
        if text in existing:
            continue
        items.append(
            {
                "text": text,
                "created_at": now.isoformat(),
                "last_hit_at": None,
                "weight": CFG.snapshot_weight_max,
            }
        )
        existing.add(text)
    return [item for item in items if item["weight"] >= CFG.snapshot_drop_weight]


def _trim_items(items: list[dict]) -> list[dict]:
    while estimate_tokens(json.dumps({"items": items}, ensure_ascii=False)) > CFG.snapshot_hard_limit_tokens:
        if not items:
            break
        lowest = min(range(len(items)), key=lambda index: items[index]["weight"])
        items.pop(lowest)
    return items


async def _reflect_impl(db: Session) -> None:
    profile = db.get(MemoryProfile, 1)
    if profile is None:
        return None
    base_revision = profile.profile_revision
    messages = list(
        reversed(
            db.scalars(
                select(ChatMessage)
                .order_by(desc(ChatMessage.idx))
                .limit(CFG.reflection_interval_turns * 2)
            ).all()
        )
    )
    items = _load_snapshot(profile.persona_snapshot)
    prompt = REFLECTION_PROMPT.format(
        snapshot=json.dumps({"items": items}, ensure_ascii=False),
        dialogue="\n".join(f"{item.role}: {item.content}" for item in messages),
        signals=_implicit_signals(messages),
    )
    try:
        raw = await model.small_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=CFG.reflection_max_output_tokens,
            temperature=CFG.temperature["reflection"],
        )
    except Exception:
        logger.exception("reflection generation failed")
        return None
    result = _parse_result(raw)
    if result is None:
        logger.warning("reflection output was not valid JSON")
        return None
    merged = _trim_items(_merge_items(items, result, _today()))
    snapshot = json.dumps({"items": merged}, ensure_ascii=False)
    current_revision = db.scalar(
        select(MemoryProfile.profile_revision).where(MemoryProfile.id == 1)
    )
    if current_revision != base_revision:
        logger.warning("reflection writeback skipped due to profile revision conflict")
        return None
    try:
        db.execute(
            update(MemoryProfile)
            .where(MemoryProfile.id == 1)
            .values(
                persona_snapshot=snapshot,
                updated_at=func.now(),
                profile_revision=MemoryProfile.profile_revision + 1,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return None


async def reflect(db: Session) -> None:
    from app.services.graph import reflection_graph

    await reflection_graph.ainvoke({}, context={"db": db})
