from collections.abc import Generator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import CFG
from app.models import Base, MemoryProfile


connect_args = {"check_same_thread": False} if CFG.database_url.startswith("sqlite") else {}
engine = create_engine(CFG.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_incremental_schema()

    from app.services.persona_catalog import seed_templates

    seed_templates(SessionLocal)

    with SessionLocal.begin() as session:
        session.execute(
            text("UPDATE memory_event SET importance = 'mid' WHERE importance = 'medium'")
        )
        session.execute(
            text("UPDATE note SET importance = 'mid' WHERE importance = 'medium'")
        )
        profile = session.execute(
            select(MemoryProfile)
            .where(MemoryProfile.id == 1)
            .with_for_update()
        ).scalar_one_or_none()
        if profile is None:
            session.add(MemoryProfile(id=1))


def _ensure_incremental_schema() -> None:
    """Add nullable columns introduced after the initial create_all schema."""
    inspector = inspect(engine)
    migrations = {
        "chat_message": {
            "conversation_id": "BIGINT NULL",
        },
        "conversation": {
            "style_preset": "VARCHAR(20) NULL",
            "conversation_mode": "VARCHAR(20) NULL",
            "custom_instructions": "TEXT NULL",
            "nickname": "VARCHAR(80) NULL",
            "relationship_level": "VARCHAR(20) NULL",
        },
        "memory_event": {
            "source_conversation_id": "BIGINT NULL",
            "hindsight_node_id": "VARCHAR(128) NULL",
        },
    }
    with engine.begin() as connection:
        for table_name, columns in migrations.items():
            existing = {item["name"] for item in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
