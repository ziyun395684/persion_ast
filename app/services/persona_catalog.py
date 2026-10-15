from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Conversation, MemoryProfile, PersonaTemplate, UserPersona
from app.prompts.persona import CONVERSATION_MODE_TEXT, L3_OUTPUT_RULES


TEMPLATES = (
    ("gentle_companion", "温柔陪伴型", "细腻、稳定地陪伴用户。", "你是温柔而可靠的陪伴者。", "gentle_warm"),
    ("genki_companion", "活泼元气型", "积极、轻快、善于接梗。", "你是活泼有感染力的陪伴者。", "genki_bounce"),
    ("wise_companion", "理性知性型", "温和理性，擅长梳理问题。", "你是理性、清晰又不失温度的陪伴者。", "gentle_warm"),
    ("quiet_listener", "安静倾听型", "少打断，多倾听和共情。", "你是安静、耐心、善于倾听的陪伴者。", "soft_milk"),
    ("efficient_assistant", "高效助手型", "优先完成任务，表达简洁明确。", "你是高效、可靠、执行力强的助手。", "gentle_warm"),
    ("easy_friend", "轻松朋友型", "自然随和，像熟悉的朋友聊天。", "你是轻松、自然、会照顾情绪的朋友。", "genki_bounce"),
    ("growth_companion", "鼓励成长型", "支持用户行动和持续成长。", "你是坚定、温暖、善于鼓励行动的陪伴者。", "gentle_warm"),
)


def seed_templates(session_factory: sessionmaker) -> None:
    with session_factory.begin() as session:
        existing = {item.code for item in session.scalars(select(PersonaTemplate)).all()}
        for code, name, description, prompt, style in TEMPLATES:
            if code not in existing:
                session.add(
                    PersonaTemplate(
                        code=code,
                        name=name,
                        description=description,
                        system_prompt=prompt,
                        default_style=style,
                        enabled=1,
                    )
                )


def ensure_user_defaults(session: Session, user_id: int) -> None:
    profile = session.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    if profile is None:
        session.add(MemoryProfile(user_id=user_id))
    if session.scalar(select(UserPersona).where(UserPersona.user_id == user_id)) is None:
        template = session.scalar(
            select(PersonaTemplate).where(PersonaTemplate.code == "gentle_companion")
        )
        if template is None:
            raise RuntimeError("persona templates are not initialized")
        session.add(UserPersona(user_id=user_id, template_id=template.id))
    session.commit()


def list_enabled_templates(session: Session) -> list[PersonaTemplate]:
    return list(
        session.scalars(
            select(PersonaTemplate)
            .where(PersonaTemplate.enabled == 1)
            .order_by(PersonaTemplate.id)
        ).all()
    )


def get_user_persona(session: Session, user_id: int) -> UserPersona:
    result = session.scalar(select(UserPersona).where(UserPersona.user_id == user_id))
    if result is not None:
        return result
    template = session.scalar(
        select(PersonaTemplate).where(PersonaTemplate.code == "gentle_companion")
    )
    if template is None:
        raise RuntimeError("persona templates are not initialized")
    result = UserPersona(user_id=user_id, template_id=template.id)
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def set_user_persona(
    session: Session,
    user_id: int,
    template_code: str,
    *,
    nickname: str | None = None,
    relationship_level: str = "close",
    custom_instructions: str | None = None,
) -> UserPersona:
    template = session.scalar(
        select(PersonaTemplate).where(
            PersonaTemplate.code == template_code,
            PersonaTemplate.enabled == 1,
        )
    )
    if template is None:
        raise ValueError("unknown persona template")
    persona = get_user_persona(session, user_id)
    persona.template_id = template.id
    persona.nickname = nickname
    persona.relationship_level = relationship_level
    persona.custom_instructions = custom_instructions
    session.commit()
    session.refresh(persona)
    return persona


def build_persona_prompt(session: Session, user_id: int, conversation_id: int | None = None) -> str:
    persona = get_user_persona(session, user_id)
    template = session.get(PersonaTemplate, persona.template_id)
    if template is None:
        raise RuntimeError("selected persona template does not exist")
    custom = persona.custom_instructions or "（无）"
    nickname = persona.nickname or "（未设置）"
    conversation = None
    if conversation_id is not None:
        conversation = session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.archived == 0,
            )
        )
    mode_text = ""
    if conversation is not None:
        nickname = conversation.nickname or nickname
        relationship = conversation.relationship_level or persona.relationship_level
        custom = conversation.custom_instructions or custom
        mode_text = CONVERSATION_MODE_TEXT.get(conversation.conversation_mode or "companion", "")
    else:
        relationship = persona.relationship_level
    return (
        f"<core_persona>\n{template.system_prompt}\n</core_persona>\n"
        f"<user_persona>\n称呼：{nickname}\n关系程度：{relationship}\n"
        f"用户补充要求：{custom}\n</user_persona>\n"
        f"<conversation_mode>\n{mode_text or '（默认陪伴模式）'}\n</conversation_mode>\n"
        f"<safety_rules>\n{L3_OUTPUT_RULES}\n</safety_rules>"
    )


def get_conversation_style(session: Session, user_id: int, conversation_id: int | None, fallback: str) -> str:
    if conversation_id is None:
        return fallback
    conversation = session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.archived == 0,
        )
    )
    return conversation.style_preset if conversation and conversation.style_preset else fallback
