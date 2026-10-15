import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import CFG
from app.models import Conversation, MemoryProfile
from app.prompts.persona import STYLE_PRESET_TEXT
from app.services import model


STYLE_CONFIRM_PROMPT = """你正在确认刚刚切换的说话风格。
用户原话：{user_msg}
新风格：{style_text}
请用小玉的口吻回复一句简短确认，体现新风格，不要解释系统规则。"""


async def switch_style(
    db: Session,
    style_preset: str,
    user_msg: str = "",
    user_id: int = 1,
    conversation_id: int | None = None,
) -> dict:
    if style_preset not in STYLE_PRESET_TEXT:
        raise ValueError(f"invalid style_preset: {style_preset}")

    profile = db.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    if profile is None:
        raise RuntimeError("memory_profile id=1 does not exist")
    if conversation_id is None:
        profile.style_preset = style_preset
        profile.profile_revision += 1
    else:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.archived == 0,
            )
        )
        if conversation is None:
            raise ValueError("conversation not found")
        conversation.style_preset = style_preset
    db.commit()

    try:
        reply = await model.chat(
            [{
                "role": "user",
                "content": STYLE_CONFIRM_PROMPT.format(
                    user_msg=user_msg, style_text=STYLE_PRESET_TEXT[style_preset]
                ),
            }],
            max_tokens=CFG.polish_model_max_tokens,
            temperature=CFG.temperature["style_switch_confirm"],
            timeout=CFG.model_timeout_sec,
        )
    except (model.ModelError, httpx.TimeoutException):
        reply = "好呀，我记住啦～"
    return {"style_preset": style_preset, "reply": reply}
