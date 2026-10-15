"""Validate a SQLite backup without modifying the live database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sqlalchemy.engine import make_url


def verify_sqlite_backup(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("verify_backup currently supports SQLite backups only")
    if not url.database:
        raise ValueError("SQLite URL does not contain a database file")
    path = Path(url.database)
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {result[0] if result else 'empty result'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a SQLite backup")
    parser.add_argument("database_url")
    args = parser.parse_args()
    verify_sqlite_backup(args.database_url)
    print("backup_ok=sqlite integrity_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
