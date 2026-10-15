import json
import logging

from app.config import CFG
from app.services.memory import estimate_tokens


logger = logging.getLogger(__name__)


def _events_tokens(events: list[dict]) -> int:
    return estimate_tokens(json.dumps(events, ensure_ascii=False, default=str))


def _summary_tokens(summary: str | None) -> int:
    return estimate_tokens(summary)


def _snapshot_tokens(snapshot_items: list[dict]) -> int:
    return estimate_tokens(json.dumps(snapshot_items, ensure_ascii=False, default=str))


def trim_data_sources(
    events: list[dict] | None,
    summary: str | None,
    snapshot_items: list[dict] | None,
    limit: int,
) -> tuple[list[dict], str | None, list[dict]]:
    """Trim structured memory sources before they are assembled into a prompt."""
    kept_events = list(events or [])
    kept_summary = summary
    kept_snapshot = list(snapshot_items or [])
    before_tokens = (
        _events_tokens(kept_events)
        + _summary_tokens(kept_summary)
        + _snapshot_tokens(kept_snapshot)
    )

    def over_limit() -> bool:
        return (
            _events_tokens(kept_events)
            + _summary_tokens(kept_summary)
            + _snapshot_tokens(kept_snapshot)
            > max(limit, 0)
        )

    while over_limit() and kept_events:
        kept_events.pop(
            min(
                range(len(kept_events)),
                key=lambda index: kept_events[index].get(
                    "score", kept_events[index].get("similarity", 0.0)
                ),
            )
        )

    if (
        over_limit()
        and kept_summary
        and len(kept_summary) > CFG.system_summary_truncate_chars
    ):
        kept_summary = kept_summary[: CFG.system_summary_truncate_chars] + "…"

    while over_limit() and kept_snapshot:
        kept_snapshot.pop(
            min(
                range(len(kept_snapshot)),
                key=lambda index: kept_snapshot[index].get("weight", 0.0),
            )
        )

    after_tokens = (
        _events_tokens(kept_events)
        + _summary_tokens(kept_summary)
        + _snapshot_tokens(kept_snapshot)
    )
    if after_tokens < before_tokens:
        logger.info(
            "system memory sources trimmed: before_tokens=%d after_tokens=%d",
            before_tokens,
            after_tokens,
        )
    return kept_events, kept_summary, kept_snapshot
