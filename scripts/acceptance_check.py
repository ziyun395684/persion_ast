"""Run a safe local API acceptance check against the running backend."""

from __future__ import annotations

import argparse
import json
import sys
from uuid import uuid4
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def request_json(
    base_url: str,
    path: str,
    payload: dict | None = None,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})} if body else (headers or {}),
        method="POST" if body else "GET",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def run_check(base_url: str, include_chat: bool = True) -> list[CheckResult]:
    checks: list[CheckResult] = []
    try:
        status, payload = request_json(base_url, "/health")
        checks.append(
            CheckResult(
                "health",
                status == 200 and payload.get("db") == "ok",
                f"status={status}, services={','.join(sorted(payload))}",
            )
        )
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        checks.append(CheckResult("health", False, type(exc).__name__))
        return checks

    try:
        username = f"acceptance-{uuid4().hex[:12]}"
        status, _ = request_json(
            base_url,
            "/auth/register",
            {"username": username, "password": "acceptance-password-123"},
        )
        if status != 201:
            raise ValueError(f"register status={status}")
        status, login_payload = request_json(
            base_url,
            "/auth/login",
            {"username": username, "password": "acceptance-password-123"},
        )
        token = login_payload.get("access_token")
        if status != 200 or not token:
            raise ValueError(f"login status={status}")
        headers = {"Authorization": f"Bearer {token}"}
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError) as exc:
        if include_chat:
            checks.append(CheckResult("chat", False, f"auth_{type(exc).__name__}"))
        checks.append(CheckResult("assistant", False, f"auth_{type(exc).__name__}"))
        return checks

    if include_chat:
        try:
            status, payload = request_json(
                base_url,
                "/chat",
                {"message": "验收测试：请简短回复"},
                headers=headers,
            )
            checks.append(
                CheckResult(
                    "chat",
                    status == 200 and isinstance(payload.get("reply"), str) and bool(payload["reply"].strip()),
                    f"status={status}, reply_present={bool(payload.get('reply'))}",
                )
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            checks.append(CheckResult("chat", False, type(exc).__name__))

    try:
        status, payload = request_json(
            base_url,
            "/assistant/query",
            {"question": "项目架构是什么？"},
            headers=headers,
        )
        checks.append(
            CheckResult(
                "assistant",
                status == 200 and isinstance(payload.get("answer"), str),
                f"status={status}, source={payload.get('source', 'unknown')}",
            )
        )
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        checks.append(CheckResult("assistant", False, type(exc).__name__))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8111")
    parser.add_argument("--skip-chat", action="store_true")
    args = parser.parse_args()

    results = run_check(args.base_url, include_chat=not args.skip_chat)
    for result in results:
        print(f"{result.name}: {'ok' if result.ok else 'failed'} ({result.detail})")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
