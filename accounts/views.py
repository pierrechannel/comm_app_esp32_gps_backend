from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import bcrypt
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.utils import timezone as dj_timezone
from django.views.decorators.csrf import csrf_exempt

from shared.audit import append_audit_log
from shared.session_tokens import create_session_token, parse_session_token

from .models import AppUser


DEFAULT_ADMIN_EMAIL = "admin@gps.local"
DEFAULT_ADMIN_PASSWORD = "admin123"
ALLOWED_ROLES = {"ADMIN", "MANAGER", "OPERATEUR", "ANALYSTE", "TECHNICIEN"}


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


def public_user_payload(user: AppUser) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "active": user.active,
        "lastLogin": user.last_login_at.isoformat().replace("+00:00", "Z") if user.last_login_at else None,
        "createdAt": user.created_at.isoformat().replace("+00:00", "Z"),
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


def _require_session(request: HttpRequest):
    session = _get_session_payload(request)
    if session is None:
        return None, json_error("Non authentifie.", status=401)
    return session, None


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


def _parse_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _validate_user_payload(body: dict, *, creating: bool):
    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip().lower()
    role = str(body.get("role", "")).strip().upper()
    active = bool(body.get("active", True))

    if len(name) < 2:
        return None, json_error("Nom invalide.", status=400)
    if not email or "@" not in email:
        return None, json_error("Email invalide.", status=400)
    if role not in ALLOWED_ROLES:
        return None, json_error("Role invalide.", status=400)

    password = str(body.get("password", ""))
    if creating:
        if len(password) < 8 or not any(char.isupper() for char in password) or not any(char.isdigit() for char in password):
            return None, json_error("Mot de passe invalide.", status=400)

    return {
        "name": name,
        "email": email,
        "role": role,
        "active": active,
        "password": password,
    }, None


def _active_admin_count() -> int:
    return AppUser.objects.filter(role="ADMIN", active=True).count()


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


@csrf_exempt
def users_view(request: HttpRequest) -> JsonResponse:
    ensure_default_user()
    session, error = _require_session(request)
    if error is not None:
        return error

    if request.method == "GET":
        role = str(request.GET.get("role", "")).strip().upper()
        active_param = request.GET.get("active")
        search = str(request.GET.get("search", "")).strip().lower()

        queryset = AppUser.objects.all().order_by("-created_at")
        if role in ALLOWED_ROLES:
            queryset = queryset.filter(role=role)
        if active_param == "true":
            queryset = queryset.filter(active=True)
        elif active_param == "false":
            queryset = queryset.filter(active=False)
        if search:
            queryset = queryset.filter(Q(email__icontains=search) | Q(name__icontains=search))

        return JsonResponse([public_user_payload(user) for user in queryset], safe=False)

    if request.method != "POST":
        return json_error("Methode non autorisee.", status=405)
    if session["role"] != "ADMIN":
        return json_error("Acces refuse.", status=403)

    try:
        body = parse_body(request)
    except ValueError:
        return json_error("Payload invalide.", status=400)

    payload, validation_error = _validate_user_payload(body, creating=True)
    if validation_error is not None:
        return validation_error

    if AppUser.objects.filter(email=payload["email"]).exists():
        return json_error("Cet email existe deja.", status=409)

    user = AppUser.objects.create(
        name=payload["name"],
        email=payload["email"],
        role=payload["role"],
        active=payload["active"],
        password_hash=make_password(payload["password"]),
    )
    append_audit_log(
        request,
        action="CREATE",
        entity="Utilisateur",
        entity_id=str(user.id),
        description=f"Utilisateur cree: {user.name} ({user.role}).",
    )
    return JsonResponse(public_user_payload(user), status=201)


@csrf_exempt
def user_detail_view(request: HttpRequest, user_id: UUID) -> JsonResponse:
    ensure_default_user()
    session, error = _require_session(request)
    if error is not None:
        return error

    user = AppUser.objects.filter(id=_parse_uuid(user_id)).first()
    if user is None:
        return json_error("Utilisateur introuvable.", status=404)

    if request.method == "GET":
        return JsonResponse(public_user_payload(user))

    if request.method == "PUT":
        if session["role"] != "ADMIN":
            return json_error("Acces refuse.", status=403)
        try:
            body = parse_body(request)
        except ValueError:
            return json_error("Payload invalide.", status=400)

        payload, validation_error = _validate_user_payload(body, creating=False)
        if validation_error is not None:
            return validation_error

        if session["id"] == str(user.id) and payload["role"] != user.role:
            return json_error("Impossible de modifier votre role.", status=403)
        if session["id"] == str(user.id) and payload["active"] is False:
            return json_error("Impossible de vous desactiver vous meme.", status=403)

        duplicate = AppUser.objects.filter(email=payload["email"]).exclude(id=user.id).exists()
        if duplicate:
            return json_error("Cet email existe deja.", status=409)

        user.name = payload["name"]
        user.email = payload["email"]
        user.role = payload["role"]
        user.active = payload["active"]
        user.save(update_fields=["name", "email", "role", "active", "updated_at"])

        append_audit_log(
            request,
            action="UPDATE",
            entity="Utilisateur",
            entity_id=str(user.id),
            description=f"Utilisateur modifie: {user.name} ({user.role}).",
        )
        return JsonResponse(public_user_payload(user))

    if request.method == "DELETE":
        if session["role"] != "ADMIN":
            return json_error("Acces refuse.", status=403)
        if session["id"] == str(user.id):
            return json_error("Impossible de vous desactiver vous meme.", status=403)
        if user.role == "ADMIN" and user.active and _active_admin_count() <= 1:
            return json_error("Impossible de desactiver le seul ADMIN actif.", status=409)

        user.active = False
        user.save(update_fields=["active", "updated_at"])
        append_audit_log(
            request,
            action="DELETE",
            entity="Utilisateur",
            entity_id=str(user.id),
            description=f"Utilisateur desactive: {user.name}.",
        )
        return JsonResponse({"success": True})

    return json_error("Methode non autorisee.", status=405)


@csrf_exempt
def user_password_view(request: HttpRequest, user_id: UUID) -> JsonResponse:
    ensure_default_user()
    session, error = _require_session(request)
    if error is not None:
        return error
    if request.method != "PUT":
        return json_error("Methode non autorisee.", status=405)

    user = AppUser.objects.filter(id=_parse_uuid(user_id)).first()
    if user is None:
        return json_error("Utilisateur introuvable.", status=404)

    can_change = session["role"] == "ADMIN" or session["id"] == str(user.id)
    if not can_change:
        return json_error("Acces refuse.", status=403)

    try:
        body = parse_body(request)
    except ValueError:
        return json_error("Payload invalide.", status=400)

    new_password = str(body.get("newPassword", ""))
    confirm_password = str(body.get("confirmPassword", ""))
    if new_password != confirm_password:
        return json_error("Les mots de passe ne correspondent pas.", status=400)
    if len(new_password) < 8 or not any(char.isupper() for char in new_password) or not any(char.isdigit() for char in new_password):
        return json_error("Mot de passe invalide.", status=400)

    user.password_hash = make_password(new_password)
    user.save(update_fields=["password_hash", "updated_at"])
    append_audit_log(
        request,
        action="UPDATE",
        entity="Utilisateur",
        entity_id=str(user.id),
        description=f"Mot de passe mis a jour pour {user.name}.",
    )
    return JsonResponse({"success": True})




