from __future__ import annotations

import json
import re

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from shared.audit import append_audit_log
from shared.session_tokens import parse_session_token

from .models import EstablishmentSettings, FinancialSettings, NotificationSettings


MONTH_RE = re.compile(r"^(0[1-9]|1[0-2])$")


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


def require_session(request: HttpRequest):
    token = request.COOKIES.get("app_session")
    if not token:
        return None
    return parse_session_token(token)


def notification_payload(instance: NotificationSettings) -> dict:
    return {
        "stockLowAlert": instance.stock_low_alert,
        "checkoutReminder": instance.checkout_reminder,
        "missingCashClose": instance.missing_cash_close,
        "dailyAutoSummary": instance.daily_auto_summary,
    }


def financial_payload(instance: FinancialSettings) -> dict:
    return {
        "currency": instance.currency,
        "taxRate": instance.tax_rate,
        "fiscalYearStart": instance.fiscal_year_start,
    }


def establishment_payload(instance: EstablishmentSettings) -> dict:
    return {
        "establishmentName": instance.establishment_name,
        "address": instance.address,
        "phone": instance.phone,
        "email": instance.email,
        "city": instance.city,
        "country": instance.country,
        "logoUrl": instance.logo_url,
    }


@csrf_exempt
def notifications_view(request: HttpRequest) -> JsonResponse:
    session = require_session(request)
    if session is None:
        return json_error("Non authentifie.", status=401)

    settings_obj, _ = NotificationSettings.objects.get_or_create(id=1)
    if request.method == "GET":
        return JsonResponse(notification_payload(settings_obj))
    if request.method != "PUT":
        return json_error("Methode non autorisee.", status=405)

    try:
        body = parse_body(request)
    except ValueError:
        return json_error("Payload invalide.")

    required_keys = {"stockLowAlert", "checkoutReminder", "missingCashClose", "dailyAutoSummary"}
    if not required_keys.issubset(body.keys()):
        return json_error("Payload invalide.")

    settings_obj.stock_low_alert = bool(body["stockLowAlert"])
    settings_obj.checkout_reminder = bool(body["checkoutReminder"])
    settings_obj.missing_cash_close = bool(body["missingCashClose"])
    settings_obj.daily_auto_summary = bool(body["dailyAutoSummary"])
    settings_obj.save()

    append_audit_log(
        request,
        action="UPDATE",
        entity="Parametres",
        description="Parametres notifications modifies.",
    )
    return JsonResponse(notification_payload(settings_obj))


@csrf_exempt
def financial_view(request: HttpRequest) -> JsonResponse:
    session = require_session(request)
    if session is None:
        return json_error("Non authentifie.", status=401)

    settings_obj, _ = FinancialSettings.objects.get_or_create(id=1)
    if request.method == "GET":
        return JsonResponse(financial_payload(settings_obj))
    if request.method != "PUT":
        return json_error("Methode non autorisee.", status=405)

    try:
        body = parse_body(request)
        currency = str(body.get("currency", "")).strip()
        tax_rate = float(body.get("taxRate"))
        fiscal_year_start = str(body.get("fiscalYearStart", ""))
    except (ValueError, TypeError):
        return json_error("Payload invalide.")

    if not currency or tax_rate < 0 or tax_rate > 100 or not MONTH_RE.match(fiscal_year_start):
        return json_error("Payload invalide.")

    settings_obj.currency = currency
    settings_obj.tax_rate = tax_rate
    settings_obj.fiscal_year_start = fiscal_year_start
    settings_obj.save()

    append_audit_log(
        request,
        action="UPDATE",
        entity="Parametres",
        description="Parametres financiers modifies.",
    )
    return JsonResponse(financial_payload(settings_obj))


@csrf_exempt
def establishment_view(request: HttpRequest) -> JsonResponse:
    session = require_session(request)
    if session is None:
        return json_error("Non authentifie.", status=401)

    settings_obj, _ = EstablishmentSettings.objects.get_or_create(id=1)
    if request.method == "GET":
        return JsonResponse(establishment_payload(settings_obj))
    if request.method != "PUT":
        return json_error("Methode non autorisee.", status=405)

    try:
        body = parse_body(request)
    except ValueError:
        return json_error("Payload invalide.")

    establishment_name = str(body.get("establishmentName", "")).strip()
    address = str(body.get("address", "")).strip()
    phone = str(body.get("phone", "")).strip()
    email = str(body.get("email", "")).strip()
    city = str(body.get("city", "")).strip()
    country = str(body.get("country", "")).strip()
    logo_url = str(body.get("logoUrl", "")).strip()

    if not establishment_name or not address or not phone or not city or not country:
        return json_error("Payload invalide.")
    if email and "@" not in email:
        return json_error("Payload invalide.")
    if logo_url and not (logo_url.startswith("http://") or logo_url.startswith("https://")):
        return json_error("Payload invalide.")

    settings_obj.establishment_name = establishment_name
    settings_obj.address = address
    settings_obj.phone = phone
    settings_obj.email = email
    settings_obj.city = city
    settings_obj.country = country
    settings_obj.logo_url = logo_url
    settings_obj.save()

    append_audit_log(
        request,
        action="UPDATE",
        entity="Parametres",
        description="Parametres etablissement modifies.",
    )
    return JsonResponse(establishment_payload(settings_obj))
