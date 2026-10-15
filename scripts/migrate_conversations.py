"""Create the conversation table in the configured database."""

from sqlalchemy import inspect, text

from app import db
from app.models import Conversation


def migrate() -> None:
    Conversation.__table__.create(bind=db.engine, checkfirst=True)
    if db.engine.dialect.name == "mysql":
        with db.engine.begin() as connection:
            conversation_columns = {item["name"] for item in inspect(connection).get_columns("conversation")}
            conversation_migrations = {
                "style_preset": "VARCHAR(20) NULL",
                "conversation_mode": "VARCHAR(20) NULL",
                "custom_instructions": "TEXT NULL",
                "nickname": "VARCHAR(80) NULL",
                "relationship_level": "VARCHAR(20) NULL",
            }
            for column_name, column_type in conversation_migrations.items():
                if column_name not in conversation_columns:
                    connection.execute(text(f"ALTER TABLE conversation ADD COLUMN {column_name} {column_type}"))
            columns = {item["name"] for item in inspect(connection).get_columns("chat_message")}
            if "conversation_id" not in columns:
                connection.execute(
                    text("ALTER TABLE chat_message ADD COLUMN conversation_id BIGINT NULL")
                )
            memory_columns = {item["name"] for item in inspect(connection).get_columns("memory_event")}
            if "source_conversation_id" not in memory_columns:
                connection.execute(
                    text("ALTER TABLE memory_event ADD COLUMN source_conversation_id BIGINT NULL")
                )
            if "hindsight_node_id" not in memory_columns:
                connection.execute(
                    text("ALTER TABLE memory_event ADD COLUMN hindsight_node_id VARCHAR(128) NULL")
                )


if __name__ == "__main__":
    migrate()
    print("conversation_migration_ok")
