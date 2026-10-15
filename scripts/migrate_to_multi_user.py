from __future__ import annotations

import secrets

from sqlalchemy import inspect, select, text

from app import db
from app.models import Base, MemoryProfile, User
from app.services import auth
from app.services.persona_catalog import ensure_user_defaults, seed_templates


SCOPED_TABLES = ("chat_message", "memory_profile", "memory_event", "todo_item", "note")


def migrate_legacy_user() -> tuple[int, str | None]:
    engine = db.engine
    Base.metadata.create_all(engine)
    generated_password = None
    with db.SessionLocal.begin() as session:
        legacy = session.scalar(select(User).where(User.username == "legacy_user"))
        if legacy is None:
            generated_password = secrets.token_urlsafe(18)
            legacy = User(
                username="legacy_user",
                password_hash=auth.hash_password(generated_password),
            )
            session.add(legacy)
            session.flush()
        legacy_id = legacy.id

    with engine.begin() as connection:
        inspector = inspect(connection)
        connection.execute(
            text(
                "ALTER TABLE memory_profile MODIFY COLUMN id BIGINT NOT NULL AUTO_INCREMENT"
            )
        )
        for table_name in SCOPED_TABLES:
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "user_id" not in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE `{table_name}` ADD COLUMN `user_id` BIGINT NOT NULL DEFAULT {legacy_id}"
                    )
                )
            else:
                connection.execute(
                    text(f"UPDATE `{table_name}` SET user_id=:user_id WHERE user_id IS NULL"),
                    {"user_id": legacy_id},
                )

        indexes = connection.execute(text("SHOW INDEX FROM chat_message")).mappings().all()
        if any(row["Key_name"] == "idx" and row["Non_unique"] == 0 for row in indexes):
            connection.execute(text("ALTER TABLE chat_message DROP INDEX `idx`"))
        _add_index_if_missing(connection, "chat_message", "uq_chat_message_user_idx", "UNIQUE KEY (`user_id`, `idx`)")
        _add_index_if_missing(connection, "memory_profile", "uq_memory_profile_user", "UNIQUE KEY (`user_id`)")

    seed_templates(db.SessionLocal)
    with db.SessionLocal() as session:
        for user in session.scalars(select(User).where(User.is_active == 1)).all():
            ensure_user_defaults(session, user.id)
    return legacy_id, generated_password


def _add_index_if_missing(connection, table: str, name: str, definition: str) -> None:
    names = {row["Key_name"] for row in connection.execute(text(f"SHOW INDEX FROM `{table}`")).mappings()}
    if name not in names:
        connection.execute(text(f"ALTER TABLE `{table}` ADD UNIQUE KEY `{name}` {definition.removeprefix('UNIQUE KEY ')}"))


def main() -> None:
    legacy_id, generated_password = migrate_legacy_user()
    print(f"multi_user_migration_ok legacy_user_id={legacy_id}")
    if generated_password:
        print(f"legacy_user_password={generated_password}")
        print("Store this password securely; it will not be shown again.")


if __name__ == "__main__":
    main()
