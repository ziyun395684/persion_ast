from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db
from app.config import CFG
from app.models import (
    ChatMessage,
    Conversation,
    MemoryEvent,
    MemoryProfile,
    Note,
    PersonaTemplate,
    TodoItem,
    User,
    UserPersona,
)
from app.services import hindsight, vector
from app.services import auth
from app.services.persona_catalog import ensure_user_defaults


router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    nickname: str | None = Field(default=None, max_length=20)

    @field_validator("username")
    @classmethod
    def username_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("username must not be blank")
        return value

    @field_validator("nickname")
    @classmethod
    def nickname_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("nickname must not be blank")
        return value


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(credentials: Credentials, session: Session = Depends(db.get_db)) -> dict:
    try:
        password_hash = auth.hash_password(credentials.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = User(username=credentials.username, password_hash=password_hash)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="username unavailable") from exc
    session.refresh(user)
    ensure_user_defaults(session, user.id)
    persona = session.scalar(select(UserPersona).where(UserPersona.user_id == user.id))
    if persona is not None and credentials.nickname is not None:
        persona.nickname = credentials.nickname
        session.commit()
        session.refresh(persona)
    return {
        "id": user.id,
        "username": user.username,
        "persona": {"nickname": persona.nickname if persona else None},
    }


@router.post("/login")
def login(
    request: Request,
    credentials: Credentials,
    session: Session = Depends(db.get_db),
) -> dict:
    key = auth.login_key(credentials.username, request.client.host if request.client else None)
    if not auth.login_allowed(key):
        raise HTTPException(
            status_code=429,
            detail="too many login attempts",
            headers={"Retry-After": str(CFG.auth_login_window_sec)},
        )
    user = session.scalar(select(User).where(User.username == credentials.username.strip()))
    if user is None or not user.is_active or not auth.verify_password(credentials.password, user.password_hash):
        auth.record_login_failure(key)
        raise HTTPException(status_code=401, detail="invalid credentials")
    auth.clear_login_failures(key)
    ensure_user_defaults(session, user.id)
    return {"access_token": auth.create_access_token(user.id), "token_type": "bearer"}


@router.get("/me")
def me(user: User = Depends(auth.get_current_user)) -> dict:
    return {"id": user.id, "username": user.username}


def _iso(value):
    return value.isoformat() if value is not None else None


@router.get("/export")
def export_account(
    session: Session = Depends(db.get_db),
    user: User = Depends(auth.get_current_user),
) -> dict:
    conversations = session.scalars(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.id)
    ).all()
    messages = session.scalars(
        select(ChatMessage).where(ChatMessage.user_id == user.id).order_by(ChatMessage.idx)
    ).all()
    events = session.scalars(
        select(MemoryEvent).where(MemoryEvent.user_id == user.id).order_by(MemoryEvent.id)
    ).all()
    todos = session.scalars(
        select(TodoItem).where(TodoItem.user_id == user.id).order_by(TodoItem.id)
    ).all()
    notes = session.scalars(
        select(Note).where(Note.user_id == user.id).order_by(Note.id)
    ).all()
    persona = session.scalar(select(UserPersona).where(UserPersona.user_id == user.id))
    template = session.get(PersonaTemplate, persona.template_id) if persona else None
    return {
        "exported_at": _iso(datetime.now()),
        "user": {"id": user.id, "username": user.username, "created_at": _iso(user.created_at)},
        "persona": {
            "template": template.code if template else None,
            "nickname": persona.nickname if persona else None,
            "relationship_level": persona.relationship_level if persona else None,
            "custom_instructions": persona.custom_instructions if persona else None,
        },
        "conversations": [
            {"id": item.id, "title": item.title, "archived": bool(item.archived), "created_at": _iso(item.created_at), "updated_at": _iso(item.updated_at)}
            for item in conversations
        ],
        "messages": [
            {"id": item.id, "conversation_id": item.conversation_id, "idx": item.idx, "role": item.role, "content": item.content, "created_at": _iso(item.created_at)}
            for item in messages
        ],
        "memory_events": [
            {"id": item.id, "event_text": item.event_text, "importance": item.importance, "happened_at": _iso(item.happened_at), "deleted": bool(item.deleted), "created_at": _iso(item.created_at)}
            for item in events
        ],
        "todos": [
            {"id": item.id, "content": item.content, "status": item.status, "due_date": _iso(item.due_date), "created_at": _iso(item.created_at)}
            for item in todos
        ],
        "notes": [
            {"id": item.id, "content": item.content, "importance": item.importance, "tags": item.tags, "created_at": _iso(item.created_at)}
            for item in notes
        ],
    }


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    session: Session = Depends(db.get_db),
    user: User = Depends(auth.get_current_user),
) -> Response:
    events = session.scalars(select(MemoryEvent).where(MemoryEvent.user_id == user.id)).all()
    for event in events:
        if event.vector_id:
            await vector.delete_event(event.vector_id)
        if event.hindsight_node_id:
            await hindsight.delete_knowledge_node(event.hindsight_node_id, user.id)

    for table in (ChatMessage, Conversation, MemoryEvent, MemoryProfile, TodoItem, Note, UserPersona):
        session.execute(delete(table).where(table.user_id == user.id))
    user.is_active = 0
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
