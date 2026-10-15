"""Create a local backup for the configured SQLite or MySQL database."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import CFG


def _default_filename(backend: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = ".db" if backend == "sqlite" else ".sql"
    return f"database-{stamp}{suffix}"


def _temporary_path(output_dir: Path, filename: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{filename}.",
        suffix=".tmp",
        dir=output_dir,
        delete=False,
    )
    handle.close()
    return Path(handle.name)


def _backup_sqlite(source_url, output_dir: Path, filename: str) -> Path:
    if not source_url.database:
        raise ValueError("SQLite URL does not contain a database file")

    source = Path(source_url.database)
    if not source.is_file():
        raise FileNotFoundError(f"SQLite database file not found: {source}")

    temporary = _temporary_path(output_dir, filename)
    destination = output_dir / filename
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _backup_mysql(source_url, output_dir: Path, filename: str, mysqldump_path: str) -> Path:
    command = [mysqldump_path]
    if source_url.host:
        command.extend(["--host", source_url.host])
    if source_url.port:
        command.extend(["--port", str(source_url.port)])
    if source_url.username:
        command.extend(["--user", source_url.username])
    if not source_url.database:
        raise ValueError("MySQL URL does not contain a database name")
    command.append(source_url.database)

    environment = os.environ.copy()
    if source_url.password is not None:
        environment["MYSQL_PWD"] = source_url.password

    destination = output_dir / filename
    temporary = _temporary_path(output_dir, filename)
    try:
        with temporary.open("wb") as stream:
            subprocess.run(
                command,
                check=True,
                stdout=stream,
                stderr=subprocess.PIPE,
                env=environment,
            )
        os.replace(temporary, destination)
    except (OSError, subprocess.CalledProcessError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("mysqldump failed; inspect the database and mysqldump logs") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def backup_database(
    database_url: str,
    output_dir: str | Path,
    filename: str | None = None,
    mysqldump_path: str = "mysqldump",
) -> Path:
    """Back up a SQLite or MySQL database and return the resulting file path."""

    url = make_url(database_url)
    backend = url.get_backend_name()
    if backend not in {"sqlite", "mysql"}:
        raise ValueError(f"unsupported database backend: {backend}")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = filename or _default_filename(backend)
    if Path(target_name).name != target_name:
        raise ValueError("filename must not contain a directory")

    if backend == "sqlite":
        return _backup_sqlite(url, target_dir, target_name)
    return _backup_mysql(url, target_dir, target_name, mysqldump_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the application database")
    parser.add_argument("--database-url", default=CFG.database_url)
    parser.add_argument("--output-dir", default="backups")
    parser.add_argument("--filename")
    parser.add_argument("--mysqldump", default="mysqldump")
    args = parser.parse_args()

    try:
        backup = backup_database(
            args.database_url,
            args.output_dir,
            filename=args.filename,
            mysqldump_path=args.mysqldump,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(f"backup_ok={backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
