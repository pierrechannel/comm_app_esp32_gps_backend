from __future__ import annotations

import asyncio
from datetime import datetime, timezone as dt_timezone

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from .models import GpsAlert, GpsLocation


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")


class GpsLiveConsumer(AsyncJsonWebsocketConsumer):
    stream_task: asyncio.Task | None = None

    async def connect(self) -> None:
        await self.accept()
        self.stream_task = asyncio.create_task(self.stream_updates())
        await self.send_json({"type": "connection.ready"})

    async def disconnect(self, close_code: int) -> None:
        if self.stream_task is not None:
            self.stream_task.cancel()
            try:
                await self.stream_task
            except asyncio.CancelledError:
                pass

    async def stream_updates(self) -> None:
        last_location_created_at, last_alert_created_at = await self.initial_cursors()

        try:
            while True:
                locations, alerts = await self.fetch_updates(last_location_created_at, last_alert_created_at)

                for payload in locations:
                    last_location_created_at = payload.pop("_cursor", last_location_created_at)
                    await self.send_json(payload)

                for payload in alerts:
                    last_alert_created_at = payload.pop("_cursor", last_alert_created_at)
                    await self.send_json(payload)

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise

    @database_sync_to_async
    def initial_cursors(self) -> tuple[datetime | None, datetime | None]:
        latest_location = GpsLocation.objects.order_by("-created_at").values_list("created_at", flat=True).first()
        latest_alert = GpsAlert.objects.order_by("-created_at").values_list("created_at", flat=True).first()
        return latest_location, latest_alert

    @database_sync_to_async
    def fetch_updates(
        self, last_location_created_at: datetime | None, last_alert_created_at: datetime | None
    ) -> tuple[list[dict], list[dict]]:
        location_queryset = GpsLocation.objects.select_related("device").order_by("created_at")
        alert_queryset = GpsAlert.objects.select_related("device").order_by("created_at")

        if last_location_created_at:
            location_queryset = location_queryset.filter(created_at__gt=last_location_created_at)
        if last_alert_created_at:
            alert_queryset = alert_queryset.filter(created_at__gt=last_alert_created_at)

        location_payloads = [
            {
                "type": "gps.location.created",
                "device": {
                    "id": str(row.device.id),
                    "deviceId": row.device.device_id,
                    "name": row.device.name,
                    "active": row.device.active,
                    "lastLocation": {
                        "lat": row.latitude,
                        "lng": row.longitude,
                        "speed": row.speed,
                        "battery": row.battery,
                        "satellites": row.satellites,
                        "timestamp": iso(row.gps_timestamp),
                    },
                },
                "location": {
                    "id": str(row.id),
                    "deviceId": row.device.device_id,
                    "lat": row.latitude,
                    "lng": row.longitude,
                    "altitude": row.altitude,
                    "speed": row.speed,
                    "satellites": row.satellites,
                    "battery": row.battery,
                    "timestamp": iso(row.gps_timestamp),
                    "createdAt": iso(row.created_at),
                },
                "_cursor": row.created_at,
            }
            for row in location_queryset[:20]
        ]

        alert_payloads = [
            {
                "type": "gps.alert.created",
                "alert": {
                    "id": str(row.id),
                    "deviceId": row.device.device_id,
                    "type": row.alert_type,
                    "message": row.message,
                    "latitude": row.latitude,
                    "longitude": row.longitude,
                    "read": row.is_read,
                    "createdAt": iso(row.created_at),
                    "deviceName": row.device.name,
                    "deviceIdentifier": row.device.device_id,
                },
                "_cursor": row.created_at,
            }
            for row in alert_queryset[:20]
        ]

        return location_payloads, alert_payloads
