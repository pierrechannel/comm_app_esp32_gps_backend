from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from django.conf import settings


SessionPayload = dict[str, Any]


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _sign(payload_part: str) -> str:
    secret = getattr(settings, "APP_SESSION_SECRET", settings.SECRET_KEY)
    digest = hmac.new(secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_session_token(user: dict[str, Any], max_age_seconds: int) -> str:
    payload: SessionPayload = {
        **user,
        "exp": int(time.time()) + max_age_seconds,
    }
    payload_part = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    return f"{payload_part}.{_sign(payload_part)}"


def parse_session_token(token: str) -> SessionPayload | None:
    try:
        if "." in token:
            payload_part, signature = token.split(".", 1)
            if not hmac.compare_digest(signature, _sign(payload_part)):
                return None
            decoded = _b64url_decode(payload_part).decode("utf-8")
        else:
            decoded = _b64url_decode(token).decode("utf-8")
        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            return None
        required = ("id", "name", "email", "role", "exp")
        if any(not payload.get(key) for key in required):
            return None
        if int(payload["exp"]) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
