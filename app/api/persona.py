from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.models import Conversation, PersonaTemplate, User
from app.services.auth import get_current_user
from app.services.graph import style_graph
from app.services.persona_catalog import get_user_persona, list_enabled_templates, set_user_persona


router = APIRouter()


class StyleRequest(BaseModel):
    style_preset: Literal["soft_milk", "genki_bounce", "gentle_warm"]
    conversation_id: int | None = Field(default=None, gt=0)


class PersonaUpdate(BaseModel):
    template_code: str = Field(min_length=1, max_length=40)
    nickname: str | None = Field(default=None, max_length=80)
    relationship_level: str = Field(default="close", max_length=20)
    custom_instructions: str | None = Field(default=None, max_length=2000)


@router.get("/persona/templates")
def persona_templates(session: Session = Depends(db.get_db)) -> list[dict]:
    return [
        {"code": item.code, "name": item.name, "description": item.description, "default_style": item.default_style}
        for item in list_enabled_templates(session)
    ]


@router.get("/persona")
def current_persona(
    user: User = Depends(get_current_user), session: Session = Depends(db.get_db)
) -> dict:
    persona = get_user_persona(session, user.id)
    template = session.get(PersonaTemplate, persona.template_id)
    return {
        "template_code": template.code,
        "template_name": template.name,
        "nickname": persona.nickname,
        "relationship_level": persona.relationship_level,
        "custom_instructions": persona.custom_instructions,
    }


@router.put("/persona")
def update_persona(
    request: PersonaUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(db.get_db),
) -> dict:
    try:
        persona = set_user_persona(
            session,
            user.id,
            request.template_code,
            nickname=request.nickname,
            relationship_level=request.relationship_level,
            custom_instructions=request.custom_instructions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    template = session.get(PersonaTemplate, persona.template_id)
    return {"template_code": template.code, "nickname": persona.nickname}


@router.post("/persona/style")
async def update_style(
    request: StyleRequest,
    session: Session = Depends(db.get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if request.conversation_id is not None:
        owned = session.scalar(
            select(Conversation).where(
                Conversation.id == request.conversation_id,
                Conversation.user_id == user.id,
                Conversation.archived == 0,
            )
        )
        if owned is None:
            raise HTTPException(status_code=404, detail="conversation not found")
    result = await style_graph.ainvoke(
        {"style_preset": request.style_preset},
        context={"db": session, "user_id": user.id, "conversation_id": request.conversation_id},
    )
    return {"style_preset": result["style_preset"], "reply": result["reply"]}
