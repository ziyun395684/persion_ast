from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


BIGINT_PRIMARY_KEY = BigInteger().with_variant(Integer, "sqlite")
TINYINT_TYPE = TINYINT().with_variant(SmallInteger, "sqlite")


class User(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[int] = mapped_column(TINYINT_TYPE, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = (Index("idx_conversation_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="新对话", server_default="新对话")
    archived: Mapped[int] = mapped_column(TINYINT_TYPE, nullable=False, default=0, server_default="0")
    style_preset: Mapped[str | None] = mapped_column(String(20))
    conversation_mode: Mapped[str | None] = mapped_column(String(20))
    custom_instructions: Mapped[str | None] = mapped_column(Text)
    nickname: Mapped[str | None] = mapped_column(String(80))
    relationship_level: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (
        UniqueConstraint("user_id", "idx", name="uq_chat_message_user_idx"),
        Index("idx_compressed", "user_id", "is_compressed", "idx"),
        Index("idx_extract", "user_id", "extract_pending", "idx"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False, default=1, server_default="1")
    conversation_id: Mapped[int | None] = mapped_column(BIGINT_PRIMARY_KEY)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Enum("user", "assistant", name="message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(20))
    task_type: Mapped[str | None] = mapped_column(String(20))
    tool_calls: Mapped[dict | list | None] = mapped_column(JSON)
    is_compressed: Mapped[int] = mapped_column(TINYINT_TYPE, nullable=False, default=0, server_default="0")
    extract_pending: Mapped[int] = mapped_column(TINYINT_TYPE, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class MemoryProfile(Base):
    __tablename__ = "memory_profile"
    __table_args__ = (UniqueConstraint("user_id", name="uq_memory_profile_user"),)

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False, default=1, server_default="1")
    summary: Mapped[str | None] = mapped_column(Text)
    persona_snapshot: Mapped[str | None] = mapped_column(Text)
    style_preset: Mapped[str] = mapped_column(String(20), nullable=False, default="soft_milk", server_default="soft_milk")
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consecutive_task_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())


class MemoryEvent(Base):
    __tablename__ = "memory_event"
    __table_args__ = (
        Index("idx_deleted", "user_id", "deleted", "id"),
        Index("idx_memory_event_source_conversation", "user_id", "source_conversation_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False, default=1, server_default="1")
    source_conversation_id: Mapped[int | None] = mapped_column(BIGINT_PRIMARY_KEY)
    event_text: Mapped[str] = mapped_column(String(500), nullable=False)
    importance: Mapped[str] = mapped_column(
        Enum("high", "mid", "low", name="memory_importance"),
        nullable=False,
        default="mid",
        server_default="mid",
    )
    vector_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    hindsight_node_id: Mapped[str | None] = mapped_column(String(128))
    happened_at: Mapped[date | None] = mapped_column(Date)
    deleted: Mapped[int] = mapped_column(TINYINT_TYPE, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class TodoItem(Base):
    __tablename__ = "todo_item"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False, default=1, server_default="1")
    content: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("open", "done", name="todo_status"),
        nullable=False,
        default="open",
        server_default="open",
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())


class Note(Base):
    __tablename__ = "note"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False, default=1, server_default="1")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[str] = mapped_column(
        Enum("high", "mid", "low", name="note_importance"),
        nullable=False,
        default="mid",
        server_default="mid",
    )
    tags: Mapped[str | None] = mapped_column(String(200))
    vector_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class PersonaTemplate(Base):
    __tablename__ = "persona_template"

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    default_style: Mapped[str] = mapped_column(String(20), nullable=False, default="soft_milk", server_default="soft_milk")
    enabled: Mapped[int] = mapped_column(TINYINT_TYPE, nullable=False, default=1, server_default="1")


class UserPersona(Base):
    __tablename__ = "user_persona"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_persona_user"),)

    id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False)
    template_id: Mapped[int] = mapped_column(BIGINT_PRIMARY_KEY, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(80))
    relationship_level: Mapped[str] = mapped_column(String(20), nullable=False, default="close", server_default="close")
    custom_instructions: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())
