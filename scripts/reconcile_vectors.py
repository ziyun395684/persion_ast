import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.reconcile import reconcile_graph


async def reconcile() -> tuple[int, int, int]:
    result = await reconcile_graph.ainvoke({})
    cleaned = result.get("cleaned", 0)
    repaired = result.get("repaired", 0)
    failed = result.get("failed", 0)
    print(f"清理 {cleaned} 条，补齐 {repaired} 条，失败 {failed} 条")
    return cleaned, repaired, failed


if __name__ == "__main__":
    asyncio.run(reconcile())
