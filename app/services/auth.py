from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.config import CFG
from app.models import User


class AuthError(ValueError):
    pass


_login_failures: dict[str, list[float]] = defaultdict(list)


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("password must contain at least 8 characters")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValueError("password must contain letters and numbers")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$16384$8$1$%s$%s" % (
        _b64encode(salt),
        _b64encode(digest),
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, n, r, p, salt_text, digest_text = encoded_hash.split("$", 5)
        if scheme != "scrypt":
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_id), "iat": now, "exp": now + CFG.auth_token_ttl_sec}
    encoded_header = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = hmac.new(CFG.auth_secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64encode(signature)}"


def decode_access_token(token: str) -> int:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
        signing_input = f"{encoded_header}.{encoded_payload}".encode()
        expected = hmac.new(CFG.auth_secret.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(encoded_signature), expected):
            raise AuthError("invalid token")
        header = json.loads(_b64decode(encoded_header))
        payload = json.loads(_b64decode(encoded_payload))
        if header.get("alg") != "HS256" or int(payload["exp"]) <= int(time.time()):
            raise AuthError("expired token")
        user_id = int(payload["sub"])
        if user_id <= 0:
            raise AuthError("invalid subject")
        return user_id
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AuthError("invalid token") from exc


def get_current_user(
    request: Request,
    session: Session = Depends(db.get_db),
) -> User:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    try:
        user_id = decode_access_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authentication") from exc
    user = session.scalar(select(User).where(User.id == user_id, User.is_active == 1))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authentication")
    return user


def login_key(username: str, client_host: str | None) -> str:
    return f"{client_host or 'unknown'}:{username.strip().casefold()}"


def login_allowed(key: str) -> bool:
    now = time.monotonic()
    failures = [item for item in _login_failures.get(key, []) if now - item < CFG.auth_login_window_sec]
    _login_failures[key] = failures
    return len(failures) < CFG.auth_login_max_attempts


def record_login_failure(key: str) -> None:
    _login_failures[key].append(time.monotonic())


def clear_login_failures(key: str) -> None:
    _login_failures.pop(key, None)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
