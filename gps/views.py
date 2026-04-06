from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from math import atan2, cos, pi, sin, sqrt
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from .ingest import expected_gps_api_key, ingest_location_payload
from .models import GpsAlert, GpsDevice, GpsLocation, GpsZone, GpsZoneDevice


def json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def parse_body(request: HttpRequest) -> dict[str, Any]:
    raw = request.body.decode("utf-8").strip()
    if not raw:
        raise ValueError("EMPTY_JSON_BODY")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("INVALID_JSON_BODY") from exc
    if not isinstance(payload, dict):
        raise ValueError("INVALID_JSON_BODY")
    return payload


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


def parse_date_param(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value.replace("Z", "+00:00"))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def parse_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def parse_limit(value: str | None) -> int:
    if not value:
        return 500
    try:
        parsed = round(float(value))
    except ValueError:
        return 500
    return max(1, min(5000, int(parsed)))


def parse_positive_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def build_paginated_response(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    safe_page = min(max(1, page), total_pages)
    start = (safe_page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "page": safe_page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }


def resolve_device_by_key(key: str) -> GpsDevice | None:
    by_device_id = GpsDevice.objects.filter(device_id__iexact=key.strip()).first()
    if by_device_id is not None:
        return by_device_id
    try:
        return GpsDevice.objects.filter(pk=key).first()
    except (ValueError, TypeError):
        return None


def distance_km(points: list[dict[str, float]]) -> float:
    total = 0.0
    for index in range(1, len(points)):
        prev = points[index - 1]
        curr = points[index]
        d_lat = (curr["lat"] - prev["lat"]) * pi / 180
        d_lng = (curr["lng"] - prev["lng"]) * pi / 180
        a = (
            sin(d_lat / 2) ** 2
            + cos(prev["lat"] * pi / 180) * cos(curr["lat"] * pi / 180) * sin(d_lng / 2) ** 2
        )
        total += 6371 * (2 * atan2(sqrt(a), sqrt(1 - a)))
    return total


def distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return distance_km([{"lat": lat1, "lng": lng1}, {"lat": lat2, "lng": lng2}]) * 1000


def is_point_in_polygon(lat: float, lng: float, polygon: list[dict[str, float]]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    j = len(polygon) - 1
    for i, point in enumerate(polygon):
        xi = point["lng"]
        yi = point["lat"]
        xj = polygon[j]["lng"]
        yj = polygon[j]["lat"]
        intersects = (yi > lat) != (yj > lat) and lng < ((xj - xi) * (lat - yi)) / ((yj - yi) or 1e-12) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def moving_minutes(points: list[dict[str, Any]]) -> float:
    total_ms = 0
    for index in range(1, len(points)):
        prev = points[index - 1]
        curr = points[index]
        if (curr.get("speed") or 0) <= 0:
            continue
        diff = int(curr["timestamp"].timestamp() * 1000) - int(prev["timestamp"].timestamp() * 1000)
        if 0 < diff < 6 * 60 * 60 * 1000:
            total_ms += diff
    return total_ms / 60000


def detect_stops(points: list[dict[str, Any]], min_duration_ms: int = 120000) -> list[dict[str, Any]]:
    stops: list[dict[str, Any]] = []
    start = -1
    for index, point in enumerate(points):
        is_slow = (point.get("speed") or 0) < 2
        if is_slow and start == -1:
            start = index
        if (not is_slow or index == len(points) - 1) and start != -1:
            end = index if is_slow and index == len(points) - 1 else index - 1
            if end >= start:
                start_ts = points[start]["timestamp"]
                end_ts = points[end]["timestamp"]
                duration = int((end_ts - start_ts).total_seconds() * 1000)
                if duration >= min_duration_ms:
                    mid = (start + end) // 2
                    stops.append(
                        {
                            "start": iso(start_ts),
                            "end": iso(end_ts),
                            "duration": duration,
                            "lat": points[mid]["lat"],
                            "lng": points[mid]["lng"],
                        }
                    )
            start = -1
    return stops


def device_payload(device: GpsDevice, last_location: GpsLocation | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(device.id),
        "deviceId": device.device_id,
        "name": device.name,
        "active": device.active,
    }
    payload["lastLocation"] = (
        {
            "lat": last_location.latitude,
            "lng": last_location.longitude,
            "speed": last_location.speed,
            "battery": last_location.battery,
            "satellites": last_location.satellites,
            "timestamp": iso(last_location.gps_timestamp),
        }
        if last_location is not None
        else None
    )
    return payload


def alert_payload(alert: GpsAlert) -> dict[str, Any]:
    return {
        "id": str(alert.id),
        "deviceId": alert.device.device_id,
        "type": alert.alert_type,
        "message": alert.message,
        "latitude": alert.latitude,
        "longitude": alert.longitude,
        "read": alert.is_read,
        "createdAt": iso(alert.created_at),
        "deviceName": alert.device.name,
        "deviceIdentifier": alert.device.device_id,
    }


def zone_payload(zone: GpsZone) -> dict[str, Any]:
    return {
        "id": str(zone.id),
        "name": zone.name,
        "type": zone.zone_type,
        "latitude": zone.latitude,
        "longitude": zone.longitude,
        "radius": zone.radius,
        "shapeType": zone.shape_type,
        "polygon": zone.polygon if zone.shape_type == "POLYGON" else [],
        "active": zone.active,
        "deviceIds": list(zone.devices.values_list("device_id", flat=True)),
        "color": zone.color,
        "createdAt": iso(zone.created_at),
        "updatedAt": iso(zone.updated_at),
    }


def ensure_device_assignments(zone: GpsZone, device_ids: list[str]) -> None:
    zone.devices.clear()
    devices = list(GpsDevice.objects.filter(device_id__in=device_ids))
    GpsZoneDevice.objects.bulk_create(
        [GpsZoneDevice(zone=zone, device=device) for device in devices],
        ignore_conflicts=True,
    )


@csrf_exempt
def devices_collection(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        page = parse_positive_int(request.GET.get("page"), 1)
        page_size = min(200, parse_positive_int(request.GET.get("pageSize"), 20))
        should_paginate = "page" in request.GET or "pageSize" in request.GET
        devices = list(GpsDevice.objects.all())
        last_locations: dict[str, GpsLocation] = {}
        for row in GpsLocation.objects.select_related("device").order_by("device_id", "-gps_timestamp"):
            last_locations.setdefault(str(row.device_id), row)
        payload = [device_payload(device, last_locations.get(str(device.id))) for device in devices]
        if should_paginate:
            return JsonResponse(build_paginated_response(payload, page, page_size))
        return JsonResponse(payload, safe=False)

    if request.method != "POST":
        return json_error("Methode non autorisee.", status=405)

    try:
        body = parse_body(request)
    except ValueError as exc:
        return json_error("JSON invalide." if str(exc) == "INVALID_JSON_BODY" else "Corps JSON vide.")

    name = str(body.get("name", "")).strip()
    device_id = str(body.get("deviceId", "")).strip()
    description = body.get("description")
    active = body.get("active", True)

    if not name or not device_id:
        return json_error("Payload invalide.")
    if GpsDevice.objects.filter(device_id__iexact=device_id).exists():
        return json_error("Ce Device ID existe deja.", status=409)

    device = GpsDevice.objects.create(
        name=name,
        device_id=device_id,
        description=str(description).strip() if isinstance(description, str) and description.strip() else None,
        active=bool(active),
    )
    return JsonResponse(
        {
            "id": str(device.id),
            "deviceId": device.device_id,
            "name": device.name,
            "description": device.description,
            "active": device.active,
            "createdAt": iso(device.created_at),
            "updatedAt": iso(device.updated_at),
        },
        status=201,
    )


@csrf_exempt
def device_detail(request: HttpRequest, device_key: str) -> JsonResponse:
    device = resolve_device_by_key(device_key)
    if device is None:
        return json_error("Appareil introuvable.", status=404)

    if request.method == "GET":
        locations = list(device.locations.order_by("-gps_timestamp")[:100])
        return JsonResponse(
            {
                "id": str(device.id),
                "deviceId": device.device_id,
                "name": device.name,
                "description": device.description,
                "active": device.active,
                "createdAt": iso(device.created_at),
                "updatedAt": iso(device.updated_at),
                "locations": [
                    {
                        "lat": row.latitude,
                        "lng": row.longitude,
                        "altitude": row.altitude,
                        "speed": row.speed,
                        "satellites": row.satellites,
                        "battery": row.battery,
                        "timestamp": iso(row.gps_timestamp),
                        "createdAt": iso(row.created_at),
                    }
                    for row in locations
                ],
            }
        )

    if request.method == "PUT":
        try:
            body = parse_body(request)
        except ValueError as exc:
            return json_error("JSON invalide." if str(exc) == "INVALID_JSON_BODY" else "Corps JSON vide.")

        name = str(body.get("name", "")).strip()
        next_device_id = str(body.get("deviceId", "")).strip()
        if not name or not next_device_id:
            return json_error("Payload invalide.")
        duplicate = GpsDevice.objects.filter(device_id__iexact=next_device_id).exclude(pk=device.id).exists()
        if duplicate:
            return json_error("Ce Device ID existe deja.", status=409)

        device.name = name
        device.device_id = next_device_id
        description = body.get("description")
        device.description = str(description).strip() if isinstance(description, str) and description.strip() else None
        if "active" in body:
            device.active = bool(body["active"])
        device.save()

        return JsonResponse(
            {
                "id": str(device.id),
                "deviceId": device.device_id,
                "name": device.name,
                "description": device.description,
                "active": device.active,
                "createdAt": iso(device.created_at),
                "updatedAt": iso(device.updated_at),
            }
        )

    if request.method == "DELETE":
        device.delete()
        return JsonResponse({"success": True})

    return json_error("Methode non autorisee.", status=405)


def device_history(request: HttpRequest, device_key: str) -> JsonResponse:
    if request.method != "GET":
        return json_error("Methode non autorisee.", status=405)

    device = resolve_device_by_key(device_key)
    if device is None:
        return json_error("Appareil introuvable.", status=404)

    from_date = parse_date_param(request.GET.get("from"))
    to_date = parse_date_param(request.GET.get("to"))

    if request.GET.get("from") and from_date is None:
        return json_error("Date 'from' invalide.")
    if request.GET.get("to") and to_date is None:
        return json_error("Date 'to' invalide.")
    if from_date and to_date and from_date > to_date:
        return json_error("La date 'from' doit etre avant 'to'.")

    queryset = device.locations.all()
    if from_date:
        queryset = queryset.filter(gps_timestamp__gte=from_date)
    if to_date:
        queryset = queryset.filter(gps_timestamp__lte=to_date)

    return JsonResponse(
        [
            {
                "lat": row.latitude,
                "lng": row.longitude,
                "altitude": row.altitude,
                "speed": row.speed,
                "satellites": row.satellites,
                "battery": row.battery,
                "timestamp": iso(row.gps_timestamp),
                "createdAt": iso(row.created_at),
            }
            for row in queryset.order_by("gps_timestamp")
        ],
        safe=False,
    )


def device_history_stats(request: HttpRequest, device_key: str) -> JsonResponse:
    if request.method != "GET":
        return json_error("Methode non autorisee.", status=405)

    device = resolve_device_by_key(device_key)
    if device is None:
        return json_error("Appareil introuvable.", status=404)

    from_date = parse_date_param(request.GET.get("from"))
    to_date = parse_date_param(request.GET.get("to"))

    if request.GET.get("from") and from_date is None:
        return json_error("Date from invalide.")
    if request.GET.get("to") and to_date is None:
        return json_error("Date to invalide.")
    if from_date and to_date and from_date > to_date:
        return json_error("La date from doit etre avant to.")

    queryset = device.locations.all()
    if from_date:
        queryset = queryset.filter(gps_timestamp__gte=from_date)
    if to_date:
        queryset = queryset.filter(gps_timestamp__lte=to_date)

    points = [
        {
            "lat": row.latitude,
            "lng": row.longitude,
            "speed": row.speed or 0,
            "timestamp": row.gps_timestamp,
        }
        for row in queryset.order_by("gps_timestamp")
    ]

    if not points:
        return JsonResponse({"distance": 0, "duration": 0, "maxSpeed": 0, "avgSpeed": 0, "stops": []})

    speeds = [point["speed"] for point in points]
    return JsonResponse(
        {
            "distance": distance_km(points),
            "duration": max(0, int((points[-1]["timestamp"] - points[0]["timestamp"]).total_seconds() * 1000)),
            "maxSpeed": max(speeds),
            "avgSpeed": sum(speeds) / len(speeds),
            "stops": detect_stops(points),
        }
    )


@csrf_exempt
def location_ingest(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return json_error("Methode non autorisee.", status=405)

    expected_api_key = expected_gps_api_key()
    if not expected_api_key:
        return json_error("GPS_API_KEY manquant dans l'environnement.", status=500)

    try:
        body = parse_body(request)
    except ValueError as exc:
        code = str(exc)
        if code == "EMPTY_JSON_BODY":
            return json_error("Corps JSON vide.")
        if code == "INVALID_JSON_BODY":
            return json_error("JSON invalide.")
        raise
    return ingest_location_payload(
        body,
        expected_api_key=expected_api_key,
        api_key=request.headers.get("x-api-key"),
    )


def locations_collection(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return json_error("Methode non autorisee.", status=405)

    from_date = parse_date_param(request.GET.get("from"))
    to_date = parse_date_param(request.GET.get("to"))
    device_id = (request.GET.get("deviceId") or "").strip()
    limit = parse_limit(request.GET.get("limit"))

    if request.GET.get("from") and from_date is None:
        return json_error("Date 'from' invalide.")
    if request.GET.get("to") and to_date is None:
        return json_error("Date 'to' invalide.")
    if from_date and to_date and from_date > to_date:
        return json_error("La date 'from' doit etre avant 'to'.")

    queryset = GpsLocation.objects.select_related("device")
    if device_id:
        queryset = queryset.filter(device__device_id=device_id)
    if from_date:
        queryset = queryset.filter(gps_timestamp__gte=from_date)
    if to_date:
        queryset = queryset.filter(gps_timestamp__lte=to_date)

    return JsonResponse(
        [
            {
                "id": str(row.id),
                "deviceId": row.device.device_id,
                "deviceName": row.device.name,
                "lat": row.latitude,
                "lng": row.longitude,
                "altitude": row.altitude,
                "speed": row.speed,
                "satellites": row.satellites,
                "battery": row.battery,
                "timestamp": iso(row.gps_timestamp),
                "createdAt": iso(row.created_at),
            }
            for row in queryset.order_by("-gps_timestamp")[:limit]
        ],
        safe=False,
    )


def alerts_collection(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return json_error("Methode non autorisee.", status=405)

    page = parse_positive_int(request.GET.get("page"), 1)
    page_size = min(200, parse_positive_int(request.GET.get("pageSize"), 20))
    should_paginate = "page" in request.GET or "pageSize" in request.GET
    queryset = GpsAlert.objects.select_related("device")
    alert_type = request.GET.get("type")
    device_id = request.GET.get("deviceId")
    from_date = parse_date_param(request.GET.get("from"))
    to_date = parse_date_param(request.GET.get("to"))
    read = parse_bool(request.GET.get("read"))

    if alert_type and alert_type != "ALL":
        queryset = queryset.filter(alert_type=alert_type)
    if device_id:
        queryset = queryset.filter(device__device_id=device_id)
    if read is not None:
        queryset = queryset.filter(is_read=read)
    if from_date:
        queryset = queryset.filter(created_at__gte=from_date)
    if to_date:
        queryset = queryset.filter(created_at__lte=to_date)

    payload = [alert_payload(alert) for alert in queryset.order_by("-created_at")]
    if should_paginate:
        return JsonResponse(build_paginated_response(payload, page, page_size))
    return JsonResponse(payload, safe=False)


@csrf_exempt
def alert_detail(request: HttpRequest, alert_id) -> JsonResponse:
    if request.method != "DELETE":
        return json_error("Methode non autorisee.", status=405)
    deleted, _ = GpsAlert.objects.filter(pk=alert_id).delete()
    if deleted == 0:
        return json_error("Alerte introuvable.", status=404)
    return JsonResponse({"success": True})


@csrf_exempt
def alert_read(request: HttpRequest, alert_id) -> JsonResponse:
    if request.method != "PUT":
        return json_error("Methode non autorisee.", status=405)
    alert = GpsAlert.objects.select_related("device").filter(pk=alert_id).first()
    if alert is None:
        return json_error("Alerte introuvable.", status=404)
    alert.is_read = True
    alert.save(update_fields=["is_read"])
    return JsonResponse(alert_payload(alert))


@csrf_exempt
def alerts_read_all(request: HttpRequest) -> JsonResponse:
    if request.method != "PUT":
        return json_error("Methode non autorisee.", status=405)
    updated = GpsAlert.objects.filter(is_read=False).update(is_read=True)
    return JsonResponse({"success": True, "updated": updated})


@csrf_exempt
def zones_collection(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return JsonResponse(
            [zone_payload(zone) for zone in GpsZone.objects.prefetch_related("devices")],
            safe=False,
        )

    if request.method != "POST":
        return json_error("Methode non autorisee.", status=405)

    try:
        body = parse_body(request)
    except ValueError as exc:
        return json_error("JSON invalide." if str(exc) == "INVALID_JSON_BODY" else "Corps JSON vide.")

    polygon = body.get("polygon") if isinstance(body.get("polygon"), list) else []
    shape_type = str(body.get("shapeType", "CIRCLE"))
    if shape_type == "POLYGON" and len(polygon) < 3:
        return json_error("Un polygone doit avoir au moins 3 points.")

    try:
        zone = GpsZone.objects.create(
            name=str(body.get("name", "")).strip(),
            zone_type=str(body.get("type", "")).strip(),
            latitude=float(body.get("latitude")),
            longitude=float(body.get("longitude")),
            radius=float(body.get("radius")),
            shape_type=shape_type,
            polygon=polygon if shape_type == "POLYGON" else [],
            active=bool(body.get("active", True)),
            color=(str(body["color"]).strip() or None) if body.get("color") is not None else None,
        )
    except (TypeError, ValueError):
        return json_error("Payload invalide.")

    ensure_device_assignments(zone, [str(item) for item in body.get("deviceIds", []) if str(item).strip()])
    return JsonResponse(zone_payload(zone), status=201)


@csrf_exempt
def zone_detail(request: HttpRequest, zone_id) -> JsonResponse:
    zone = GpsZone.objects.prefetch_related("devices").filter(pk=zone_id).first()
    if zone is None:
        return json_error("Zone introuvable.", status=404)

    if request.method == "PUT":
        try:
            body = parse_body(request)
        except ValueError as exc:
            return json_error("JSON invalide." if str(exc) == "INVALID_JSON_BODY" else "Corps JSON vide.")

        polygon = body.get("polygon") if isinstance(body.get("polygon"), list) else []
        shape_type = str(body.get("shapeType", "CIRCLE"))
        if shape_type == "POLYGON" and len(polygon) < 3:
            return json_error("Un polygone doit avoir au moins 3 points.")

        try:
            zone.name = str(body.get("name", "")).strip()
            zone.zone_type = str(body.get("type", "")).strip()
            zone.latitude = float(body.get("latitude"))
            zone.longitude = float(body.get("longitude"))
            zone.radius = float(body.get("radius"))
            zone.shape_type = shape_type
            zone.polygon = polygon if shape_type == "POLYGON" else []
            zone.active = bool(body.get("active"))
            zone.color = (str(body["color"]).strip() or None) if body.get("color") is not None else None
        except (TypeError, ValueError):
            return json_error("Payload invalide.")

        zone.save()
        ensure_device_assignments(zone, [str(item) for item in body.get("deviceIds", []) if str(item).strip()])
        return JsonResponse(zone_payload(zone))

    if request.method == "DELETE":
        zone.delete()
        return JsonResponse({"success": True})

    return json_error("Methode non autorisee.", status=405)


def reports_summary(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return json_error("Methode non autorisee.", status=405)

    from_date = parse_date_param(request.GET.get("from"))
    to_date = parse_date_param(request.GET.get("to"))
    device_id = request.GET.get("deviceId")

    if request.GET.get("from") and from_date is None:
        return json_error("Date from invalide.")
    if request.GET.get("to") and to_date is None:
        return json_error("Date to invalide.")
    if from_date and to_date and from_date > to_date:
        return json_error("La date from doit etre avant to.")

    devices = list(GpsDevice.objects.all())
    selected_ids = {device_id} if device_id and device_id != "ALL" else {device.device_id for device in devices}
    device_names = {device.device_id: device.name for device in devices}

    location_queryset = GpsLocation.objects.select_related("device").filter(device__device_id__in=selected_ids)
    alert_queryset = GpsAlert.objects.select_related("device").filter(device__device_id__in=selected_ids)
    if from_date:
        location_queryset = location_queryset.filter(gps_timestamp__gte=from_date)
        alert_queryset = alert_queryset.filter(created_at__gte=from_date)
    if to_date:
        location_queryset = location_queryset.filter(gps_timestamp__lte=to_date)
        alert_queryset = alert_queryset.filter(created_at__lte=to_date)

    locations = list(location_queryset.order_by("gps_timestamp"))
    alerts = list(alert_queryset.order_by("-created_at"))

    by_device_rows: dict[str, list[dict[str, Any]]] = {}
    battery_groups: dict[str, dict[str, Any]] = {}
    for row in locations:
        dev_id = row.device.device_id
        by_device_rows.setdefault(dev_id, []).append(
            {
                "latitude": row.latitude,
                "longitude": row.longitude,
                "speed": row.speed or 0,
                "timestamp": row.gps_timestamp,
            }
        )
        if row.battery is not None:
            day = row.gps_timestamp.astimezone(dt_timezone.utc).date().isoformat()
            key = f"{dev_id}-{day}"
            if key not in battery_groups:
                battery_groups[key] = {
                    "date": day,
                    "deviceId": dev_id,
                    "name": device_names.get(dev_id, dev_id),
                    "sum": row.battery,
                    "count": 1,
                }
            else:
                battery_groups[key]["sum"] += row.battery
                battery_groups[key]["count"] += 1

    by_device: list[dict[str, Any]] = []
    total_distance = 0.0
    total_duration = 0.0
    total_stops = 0

    for dev_id, rows in by_device_rows.items():
        coords = [{"lat": row["latitude"], "lng": row["longitude"]} for row in rows]
        stat_points = [
            {
                "lat": row["latitude"],
                "lng": row["longitude"],
                "speed": row["speed"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]
        speeds = [row["speed"] for row in rows]
        distance = distance_km(coords)
        duration = moving_minutes(stat_points)
        stops = len(detect_stops(stat_points))
        alert_count = len([alert for alert in alerts if alert.device.device_id == dev_id])

        total_distance += distance
        total_duration += duration
        total_stops += stops

        by_device.append(
            {
                "deviceId": dev_id,
                "name": device_names.get(dev_id, dev_id),
                "distance": distance,
                "duration": duration,
                "maxSpeed": max(speeds) if speeds else 0,
                "avgSpeed": (sum(speeds) / len(speeds)) if speeds else 0,
                "alertCount": alert_count,
                "stops": stops,
            }
        )

    by_device.sort(key=lambda item: item["distance"], reverse=True)

    daily_distance: list[dict[str, Any]] = []
    for dev_id, rows in by_device_rows.items():
        days: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            day = row["timestamp"].astimezone(dt_timezone.utc).date().isoformat()
            days.setdefault(day, []).append(row)
        for day, values in days.items():
            daily_distance.append(
                {
                    "date": day,
                    "distance": distance_km(
                        [{"lat": value["latitude"], "lng": value["longitude"]} for value in values]
                    ),
                    "deviceId": dev_id,
                    "name": device_names.get(dev_id, dev_id),
                }
            )
    daily_distance.sort(key=lambda item: item["date"])

    alerts_by_day_map: dict[str, dict[str, Any]] = {}
    for alert in alerts:
        day = alert.created_at.astimezone(dt_timezone.utc).date().isoformat()
        alerts_by_day_map.setdefault(day, {"date": day, "SPEEDING": 0, "LOW_BATTERY": 0, "SIGNAL_LOST": 0})
        if alert.alert_type in {"SPEEDING", "LOW_BATTERY", "SIGNAL_LOST"}:
            alerts_by_day_map[day][alert.alert_type] += 1
    alerts_by_day = sorted(alerts_by_day_map.values(), key=lambda item: item["date"])

    battery_history = sorted(
        [
            {
                "date": row["date"],
                "deviceId": row["deviceId"],
                "name": row["name"],
                "avgBattery": row["sum"] / row["count"] if row["count"] else 0,
            }
            for row in battery_groups.values()
        ],
        key=lambda item: item["date"],
    )

    return JsonResponse(
        {
            "totalDistance": total_distance,
            "totalDuration": total_duration,
            "totalAlerts": len(alerts),
            "speedingAlerts": len([alert for alert in alerts if alert.alert_type == "SPEEDING"]),
            "batteryAlerts": len([alert for alert in alerts if alert.alert_type == "LOW_BATTERY"]),
            "signalLostAlerts": len([alert for alert in alerts if alert.alert_type == "SIGNAL_LOST"]),
            "totalStops": total_stops,
            "byDevice": by_device,
            "dailyDistance": daily_distance,
            "alertsByDay": alerts_by_day,
            "batteryHistory": battery_history,
        }
    )
