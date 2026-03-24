from __future__ import annotations

from django.http import HttpRequest

from .session_tokens import parse_session_token


def _get_request_ip(request: HttpRequest) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.headers.get("x-real-ip")


def append_audit_log(
    request: HttpRequest,
    *,
    action: str,
    entity: str,
    description: str,
    entity_id: str | None = None,
) -> None:
    from accounts.models import AuditLog

    token = request.COOKIES.get("app_session")
    session = parse_session_token(token) if token else None
    AuditLog.objects.create(
        user_id_value=str(session.get("id")) if session else "system",
        user_name=str(session.get("name")) if session else "Systeme",
        user_role=str(session.get("role")) if session else "SYSTEM",
        action=action,
        entity=entity,
        entity_id_value=entity_id,
        description=description,
        ip_address=_get_request_ip(request),
    )
