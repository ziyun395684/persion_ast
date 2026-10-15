import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import CFG
from app.services import hindsight


MENTAL_MODELS = [
    {
        "model_id": "user-profile",
        "name": "用户画像",
        "source_query": "这个用户的技术栈是什么？代码偏好？常用工具有哪些？",
    },
    {
        "model_id": "project-context",
        "name": "项目上下文",
        "source_query": "当前项目的架构是什么？用了哪些技术？关键决策有哪些？",
    },
    {
        "model_id": "work-patterns",
        "name": "工作模式",
        "source_query": "用户的工作习惯是什么？什么时候效率高？喜欢什么样的沟通方式？",
    },
]


async def initialize() -> None:
    if not CFG.hindsight_enabled:
        print("Hindsight is disabled; set HINDSIGHT_ENABLED=true to initialize models.")
        return

    try:
        existing = await hindsight.list_mental_models()
        existing_ids = {
            item.get("id") or item.get("model_id")
            for item in existing
            if isinstance(item, dict)
        }
        for item in MENTAL_MODELS:
            if item["model_id"] in existing_ids:
                print(f"exists: {item['model_id']}")
                continue
            created = await hindsight.create_mental_model(**item)
            print(f"{'created' if created else 'failed'}: {item['model_id']}")
    finally:
        await hindsight.close()


if __name__ == "__main__":
    asyncio.run(initialize())
