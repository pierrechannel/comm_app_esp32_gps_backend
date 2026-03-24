from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from math import atan2, cos, pi, sin, sqrt
from typing import Any

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import GpsAlert, GpsDevice, GpsLocation, GpsZone


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


def ingest_location_payload(body: dict[str, Any], *, expected_api_key: str | None = None, api_key: str | None = None) -> JsonResponse:
    if expected_api_key is not None and api_key != expected_api_key:
        return JsonResponse({"error": "Cle API invalide."}, status=401)

    try:
        device_id = str(body.get("device_id", "")).strip()
        lat = float(body["lat"])
        lng = float(body["lng"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Payload invalide."}, status=400)

    if not device_id or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return JsonResponse({"error": "Payload invalide."}, status=400)

    timestamp = timezone.now()
    raw_timestamp = body.get("timestamp")
    if raw_timestamp is not None:
        if isinstance(raw_timestamp, str):
            parsed = parse_datetime(raw_timestamp.replace("Z", "+00:00"))
            if parsed is not None:
                timestamp = parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
            else:
                try:
                    raw_timestamp = float(raw_timestamp)
                except ValueError:
                    return JsonResponse({"error": "Timestamp invalide."}, status=400)
        if isinstance(raw_timestamp, (int, float)) and raw_timestamp >= 1_000_000_000:
            if raw_timestamp <= 1_000_000_000_000:
                raw_timestamp = raw_timestamp * 1000
            timestamp = datetime.fromtimestamp(raw_timestamp / 1000, tz=dt_timezone.utc)

    gps_fix = body.get("gps_fix")
    if gps_fix is False and abs(lat) < 1e-7 and abs(lng) < 1e-7:
        return JsonResponse(
            {"success": True, "message": "Fix GPS indisponible. Position non enregistree."},
            status=202,
        )

    device, _ = GpsDevice.objects.get_or_create(
        device_id=device_id,
        defaults={"name": device_id, "active": True},
    )

    location = GpsLocation.objects.create(
        device=device,
        latitude=lat,
        longitude=lng,
        altitude=float(body["alt"]) if body.get("alt") is not None else None,
        speed=float(body["speed"]) if body.get("speed") is not None else None,
        satellites=int(body["satellites"]) if body.get("satellites") is not None else None,
        battery=float(body["battery"]) if body.get("battery") is not None else None,
        gps_timestamp=timestamp,
    )

    alerts_to_create: list[GpsAlert] = []
    if location.speed is not None and location.speed > 120:
        alerts_to_create.append(
            GpsAlert(
                device=device,
                alert_type="SPEEDING",
                message="Vitesse excessive detectee.",
                latitude=lat,
                longitude=lng,
            )
        )
    if location.battery is not None and location.battery < 20:
        alerts_to_create.append(
            GpsAlert(
                device=device,
                alert_type="LOW_BATTERY",
                message="Batterie faible.",
                latitude=lat,
                longitude=lng,
            )
        )

    for zone in GpsZone.objects.filter(active=True, devices=device):
        polygon = zone.polygon if isinstance(zone.polygon, list) else []
        inside_zone = (
            is_point_in_polygon(lat, lng, polygon)
            if zone.shape_type == "POLYGON" and len(polygon) >= 3
            else distance_meters(lat, lng, zone.latitude, zone.longitude) < zone.radius
        )
        if inside_zone and zone.zone_type == "INTERDITE":
            alerts_to_create.append(
                GpsAlert(
                    device=device,
                    alert_type="OUT_OF_ZONE",
                    message=f"Zone interdite: {zone.name}",
                    latitude=lat,
                    longitude=lng,
                )
            )
        if not inside_zone and zone.zone_type == "AUTORISEE":
            alerts_to_create.append(
                GpsAlert(
                    device=device,
                    alert_type="OUT_OF_ZONE",
                    message=f"Sortie zone autorisee: {zone.name}",
                    latitude=lat,
                    longitude=lng,
                )
            )

    if alerts_to_create:
        GpsAlert.objects.bulk_create(alerts_to_create)

    return JsonResponse({"success": True, "message": "Location recorded"}, status=201)


def expected_gps_api_key() -> str:
    return getattr(settings, "GPS_API_KEY", "")
