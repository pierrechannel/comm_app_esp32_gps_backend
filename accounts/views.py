from __future__ import annotations

import json
from datetime import datetime, timezone

import bcrypt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.http import HttpRequest, JsonResponse
from django.utils import timezone as dj_timezone
from django.views.decorators.csrf import csrf_exempt

from shared.audit import append_audit_log
from shared.session_tokens import create_session_token, parse_session_token

from .models import AppUser


DEFAULT_ADMIN_EMAIL = "admin@hotel.local"
DEFAULT_ADMIN_PASSWORD = "admin123"


def json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def parse_body(request: HttpRequest) -> dict:
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise ValueError("INVALID_JSON")
    if not isinstance(data, dict):
        raise ValueError("INVALID_JSON")
    return data


def user_payload(user: AppUser) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
    }


def _is_legacy_bcrypt(value: str) -> bool:
    return value.startswith("$2a$") or value.startswith("$2b$") or value.startswith("$2y$")


def verify_password_hash(stored: str, incoming: str) -> bool:
    if not stored:
        return False
    if _is_legacy_bcrypt(stored):
        try:
            return bcrypt.checkpw(incoming.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    if "$" in stored:
        try:
            return check_password(incoming, stored)
        except ValueError:
            return False
    return stored == incoming


def ensure_default_user() -> None:
    if AppUser.objects.exists():
        return
    AppUser.objects.create(
        name="Admin Principal",
        email=DEFAULT_ADMIN_EMAIL,
        role="ADMIN",
        active=True,
        password_hash=make_password(DEFAULT_ADMIN_PASSWORD),
    )


def _get_session_payload(request: HttpRequest):
    token = request.COOKIES.get("app_session")
    if not token:
        return None
    return parse_session_token(token)


def _set_session_cookie(response: JsonResponse, token: str, max_age_seconds: int) -> JsonResponse:
    response.set_cookie(
        "app_session",
        token,
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
        path="/",
        max_age=max_age_seconds,
    )
    return response


@csrf_exempt
def login_view(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return json_error("Methode non autorisee.", status=405)

    ensure_default_user()
    try:
        body = parse_body(request)
    except ValueError:
        return json_error("Identifiants invalides.")

    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    remember = bool(body.get("remember", False))

    if not email or not password or "@" not in email:
        return json_error("Identifiants invalides.")

    user = AppUser.objects.filter(email=email).first()
    if user is None:
        return json_error("Email ou mot de passe incorrect.", status=401)
    if not user.active:
        return json_error("Compte desactive.", status=403)
    if not verify_password_hash(user.password_hash, password):
        return json_error("Email ou mot de passe incorrect.", status=401)

    if not user.password_hash.startswith("pbkdf2_"):
        user.password_hash = make_password(password)
    user.last_login_at = dj_timezone.now()
    user.save(update_fields=["password_hash", "last_login_at", "updated_at"])

    max_age_seconds = 60 * 60 * 24 * 30 if remember else 60 * 60 * 12
    token = create_session_token(user_payload(user), max_age_seconds)
    response = JsonResponse({"user": user_payload(user)})
    append_audit_log(
        request,
        action="LOGIN",
        entity="Session",
        entity_id=str(user.id),
        description=f"Connexion utilisateur: {user.name}.",
    )
    return _set_session_cookie(response, token, max_age_seconds)


@csrf_exempt
def logout_view(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return json_error("Methode non autorisee.", status=405)

    append_audit_log(
        request,
        action="LOGOUT",
        entity="Session",
        description="Deconnexion utilisateur.",
    )
    response = JsonResponse({"success": True})
    response.set_cookie(
        "app_session",
        "",
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
        path="/",
        max_age=0,
    )
    return response


def me_view(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return json_error("Methode non autorisee.", status=405)
    session = _get_session_payload(request)
    if session is None:
        return json_error("Non authentifie.", status=401)
    return JsonResponse({"user": {"id": session["id"], "name": session["name"], "email": session["email"], "role": session["role"]}})


def session_view(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return json_error("Methode non autorisee.", status=405)
    session = _get_session_payload(request)
    if session is None:
        return JsonResponse(None, safe=False)
    expires = datetime.fromtimestamp(int(session["exp"]), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return JsonResponse(
        {
            "user": {"id": session["id"], "name": session["name"], "email": session["email"], "role": session["role"]},
            "expires": expires,
        }
    )
