from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import Date, DateTime, create_engine, select
from sqlalchemy.engine import Engine

from app.models import Base, ChatMessage, MemoryEvent, MemoryProfile, Note, TodoItem


MIGRATION_TABLES = (ChatMessage, MemoryProfile, MemoryEvent, TodoItem, Note)


def migrate_database(source_url: str, target_url: str) -> dict[str, int]:
    """Copy the application tables from source to an empty or identical target."""
    source = create_engine(source_url)
    target = create_engine(target_url)
    Base.metadata.create_all(target)

    result: dict[str, int] = {}
    with source.connect() as source_connection, target.begin() as target_connection:
        for model in MIGRATION_TABLES:
            table = model.__table__
            source_rows = _read_source_rows(source_connection, table.name)
            target_rows = list(target_connection.execute(select(table)).mappings())
            if target_rows and not _rows_equal(source_rows, target_rows):
                raise RuntimeError(
                    f"target table {table.name} is non-empty and differs from source"
                )
            if not target_rows and source_rows:
                target_connection.execute(table.insert(), [dict(row) for row in source_rows])
            result[table.name] = len(source_rows)
    return result


def _rows_equal(left: Iterable[object], right: Iterable[object]) -> bool:
    return sorted((_stable_row(row) for row in left), key=repr) == sorted(
        (_stable_row(row) for row in right), key=repr
    )


def _stable_row(row: object) -> tuple[tuple[str, str], ...]:
    mapping = dict(row)
    return tuple(sorted((key, repr(value)) for key, value in mapping.items()))


def _read_source_rows(connection, table_name: str) -> list[dict]:
    """Read legacy rows without SQLAlchemy enum processors rejecting old values."""
    result = connection.exec_driver_sql(f"SELECT * FROM {table_name}")
    rows = []
    for row in result:
        item = dict(zip(result.keys(), row))
        if item.get("importance") == "medium":
            item["importance"] = "mid"
        for column in Base.metadata.tables[table_name].columns:
            value = item.get(column.name)
            if isinstance(column.type, DateTime) and isinstance(value, str):
                item[column.name] = datetime.fromisoformat(value)
            elif isinstance(column.type, Date) and not isinstance(column.type, DateTime) and isinstance(value, str):
                item[column.name] = date.fromisoformat(value)
        rows.append(item)
    return rows
