import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import CFG
from app.services import hindsight


async def check() -> int:
    if not CFG.hindsight_enabled:
        print("Hindsight disabled: set HINDSIGHT_ENABLED=true to run integration checks.")
        return 0

    try:
        healthy = await hindsight.is_healthy()
        print(f"health: {'ok' if healthy else 'failed'}")
        if not healthy:
            return 1

        retained = await hindsight.retain(
            "Hindsight integration check: this is a disposable test memory.",
            context="integration-check",
            tags=["source:integration-check"],
        )
        print(f"retain: {'ok' if retained else 'failed'}")
        if not retained:
            return 1

        recalled = await hindsight.recall("Hindsight integration check", budget="low")
        print(f"recall: {len(recalled)} result(s)")

        models = await hindsight.list_mental_models()
        print(f"mental_models: {len(models)} model(s)")
        return 0
    finally:
        await hindsight.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
