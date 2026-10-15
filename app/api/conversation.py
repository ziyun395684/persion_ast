from fastapi import APIRouter, Depends, HTTPException, status
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.models import Conversation, MemoryProfile, PersonaTemplate, User
from app.services.auth import get_current_user
from app.services.conversation import delete_conversation
from app.services.persona_catalog import get_user_persona


router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=120)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationPersonaUpdate(BaseModel):
    style_preset: Literal["soft_milk", "genki_bounce", "gentle_warm"] | None = None
    conversation_mode: Literal["companion", "consulting", "study", "work"] | None = None
    custom_instructions: str | None = Field(default=None, max_length=2000)
    nickname: str | None = Field(default=None, max_length=80)
    relationship_level: str | None = Field(default=None, max_length=20)


def _serialize(item: Conversation) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "archived": bool(item.archived),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("")
def list_conversations(
    include_archived: bool = False,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    statement = select(Conversation).where(Conversation.user_id == user.id)
    if not include_archived:
        statement = statement.where(Conversation.archived == 0)
    items = session.scalars(statement.order_by(Conversation.updated_at.desc(), Conversation.id.desc())).all()
    return [_serialize(item) for item in items]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_conversation(
    request: ConversationCreate,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    item = Conversation(user_id=user.id, title=request.title.strip())
    session.add(item)
    session.commit()
    session.refresh(item)
    return _serialize(item)


def _get_owned_conversation(session: Session, user_id: int, conversation_id: int) -> Conversation:
    item = session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.archived == 0,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return item


@router.put("/{conversation_id}")
def update_conversation(
    conversation_id: int,
    request: ConversationUpdate,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    item = _get_owned_conversation(session, user.id, conversation_id)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title must not be blank")
    item.title = title
    session.commit()
    session.refresh(item)
    return _serialize(item)


def _persona_payload(session: Session, user_id: int, item: Conversation) -> dict:
    persona = get_user_persona(session, user_id)
    profile = session.scalar(select(MemoryProfile).where(MemoryProfile.user_id == user_id))
    template = session.get(PersonaTemplate, persona.template_id)
    return {
        "conversation_id": item.id,
        "overrides": {
            "style_preset": item.style_preset,
            "conversation_mode": item.conversation_mode,
            "custom_instructions": item.custom_instructions,
            "nickname": item.nickname,
            "relationship_level": item.relationship_level,
        },
        "effective": {
            "template_code": template.code if template else None,
            "style_preset": item.style_preset or (profile.style_preset if profile else "soft_milk"),
            "conversation_mode": item.conversation_mode or "companion",
            "custom_instructions": item.custom_instructions or persona.custom_instructions,
            "nickname": item.nickname or persona.nickname,
            "relationship_level": item.relationship_level or persona.relationship_level,
        },
    }


@router.get("/{conversation_id}/persona")
def get_conversation_persona(
    conversation_id: int,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    item = _get_owned_conversation(session, user.id, conversation_id)
    return _persona_payload(session, user.id, item)


@router.put("/{conversation_id}/persona")
def update_conversation_persona(
    conversation_id: int,
    request: ConversationPersonaUpdate,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    item = _get_owned_conversation(session, user.id, conversation_id)
    item.style_preset = request.style_preset
    item.conversation_mode = request.conversation_mode
    item.custom_instructions = request.custom_instructions
    item.nickname = request.nickname
    item.relationship_level = request.relationship_level
    session.commit()
    session.refresh(item)
    return _persona_payload(session, user.id, item)


@router.delete("/{conversation_id}")
def archive_conversation(
    conversation_id: int,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    import asyncio

    result = asyncio.run(delete_conversation(session, user.id, conversation_id))
    if not result["found"]:
        raise HTTPException(status_code=404, detail="conversation not found")
    return result


@router.delete("/{conversation_id}/forget")
def forget_conversation(
    conversation_id: int,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    import asyncio

    result = asyncio.run(delete_conversation(session, user.id, conversation_id, forget=True))
    if not result["found"]:
        raise HTTPException(status_code=404, detail="conversation not found")
    return result
