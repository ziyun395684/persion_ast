import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import CFG
from app.models import MemoryProfile
from app.prompts.persona import L0_CORE_PERSONA, L3_OUTPUT_RULES, STYLE_PRESET_TEXT
from app.services.message import recent_messages
from app.services import vector
from app.services.memory import estimate_tokens
from app.services.trim import trim_data_sources
from app.services import hindsight
from app.services.persona_catalog import build_persona_prompt, get_conversation_style


async def build_prompt(
    db: Session,
    user_msg: str,
    include_recall: bool = True,
    user_id: int = 1,
    conversation_id: int | None = None,
) -> list[dict[str, str]]:
    result = await build_prompt_context(
        db, user_msg, user_id=user_id, include_recall=include_recall, conversation_id=conversation_id
    )
    return result["prompt"]


async def build_prompt_context(
    db: Session,
    user_msg: str,
    user_id: int = 1,
    include_recall: bool = True,
    conversation_id: int | None = None,
    prefetched_recalled: list[dict] | None = None,
    include_hindsight: bool = True,
) -> dict:
    profile = db.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    style_key = get_conversation_style(
        db,
        user_id,
        conversation_id,
        profile.style_preset if profile else "soft_milk",
    )
    style_text = STYLE_PRESET_TEXT.get(style_key, STYLE_PRESET_TEXT["soft_milk"])
    if prefetched_recalled is not None:
        recalled = prefetched_recalled
    else:
        recalled = (
            await vector.search(
                user_msg,
                k=CFG.recall_top_k,
                min_score=CFG.recall_min_score,
                user_id=user_id,
            )
            if include_recall
            else []
        )
    recalled.sort(
        key=lambda item: item["similarity"] * CFG.importance_weight.get(item.get("importance", "mid"), 0.7),
        reverse=True,
    )
    hindsight_events = []
    if include_hindsight and CFG.hindsight_recall_enabled:
        recalled_from_hindsight = await hindsight.recall(user_msg, budget="mid", user_id=user_id)
        hindsight_events = [
            {
                "text": item.get("text", ""),
                "type": item.get("type", "unknown"),
                "score": 0.0,
                "source": "Hindsight",
            }
            for item in recalled_from_hindsight
            if item.get("text")
        ]
    prompt_events = [
        {**item, "source": "L3"} for item in recalled
    ] + hindsight_events
    snapshot_items = _parse_snapshot(profile.persona_snapshot if profile else None)
    persona_prompt = build_persona_prompt(db, user_id, conversation_id)
    base_system = _assemble_system(persona_prompt, style_text, None, [], [])
    available_tokens = max(CFG.system_token_limit - estimate_tokens(base_system), 0)
    recalled, summary, snapshot_items = trim_data_sources(
        prompt_events,
        profile.summary if profile else None,
        snapshot_items,
        limit=available_tokens,
    )
    system_prompt = _assemble_system(persona_prompt, style_text, summary, snapshot_items, prompt_events)
    recalled = [item for item in prompt_events if item.get("source") == "L3"]

    prompt = [{"role": "system", "content": system_prompt}]
    history = await recent_messages(
        db, limit=16, user_id=user_id, conversation_id=conversation_id
    )
    prompt.extend({"role": item.role, "content": item.content} for item in history)
    if not history or history[-1].role != "user" or history[-1].content != user_msg:
        prompt.append({"role": "user", "content": user_msg})
    return {
        "prompt": prompt,
        "recalled_events": recalled,
        "l2_summary": summary,
    }


def _parse_snapshot(raw_snapshot: str | None) -> list[dict]:
    if not raw_snapshot:
        return []
    try:
        value = json.loads(raw_snapshot)
    except (TypeError, ValueError):
        return []
    items = value.get("items") if isinstance(value, dict) else value
    return items if isinstance(items, list) else []


def _assemble_system(
    persona_prompt: str,
    style_text: str,
    summary: str | None,
    snapshot_items: list[dict],
    events: list[dict],
) -> str:
    snapshot_text = "\n".join(
        f"- {item.get('text', '')}" for item in snapshot_items if item.get("text")
    ) or "（暂无）"
    summary_text = summary or "（暂无）"
    events_text = "\n".join(
        f"- [来源: {item.get('source', 'L3')}] {item.get('text', '')}"
        for item in events
        if item.get("text")
    ) or "（暂无）"
    return (
        f"<persona>\n{L0_CORE_PERSONA}\n{persona_prompt}\n\n风格：{style_text}\n</persona>\n"
        f"<memory>\n<snapshot>\n{snapshot_text}\n</snapshot>\n"
        f"<summary>\n{summary_text}\n</summary>\n"
        f"<events>\n{events_text}\n</events>\n</memory>\n"
        f"<rules>\n{L3_OUTPUT_RULES}\n</rules>"
    )
