import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db
from app.services.message import increment_turn_count


async def main() -> None:
    init_db()
    with SessionLocal() as db:
        values = [await increment_turn_count(db) for _ in range(5)]
    print(f"turn_count values: {values}")


if __name__ == "__main__":
    asyncio.run(main())
