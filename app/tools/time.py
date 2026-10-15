from datetime import datetime
from zoneinfo import ZoneInfo


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")


def _time_now_impl() -> dict:
    now = datetime.now(SHANGHAI_TZ)
    return {
        "ok": True,
        "data": f"{now:%Y-%m-%d %H:%M:%S} 星期{WEEKDAYS[now.weekday()]}",
        "error": None,
    }


def time_now() -> dict:
    from app.services.graph import time_graph

    result = time_graph.invoke({"operation": "now"})
    return {key: result.get(key) for key in ("ok", "data", "error")}
