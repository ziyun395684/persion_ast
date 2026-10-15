import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db
from app.services.message import save_message


async def main() -> None:
    init_db()
    with SessionLocal() as db:
        for content in ("测试消息 1", "测试消息 2", "测试消息 3"):
            message = await save_message(db, "user", content)
            print(f"saved idx={message.idx} content={message.content}")


if __name__ == "__main__":
    asyncio.run(main())
