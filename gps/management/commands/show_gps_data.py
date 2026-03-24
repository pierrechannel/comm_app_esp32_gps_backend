from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from gps.models import GpsDevice, GpsLocation


class Command(BaseCommand):
    help = "Show recently saved GPS devices and locations from the configured Django database."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Number of recent locations to display.")
        parser.add_argument("--device-id", type=str, default="", help="Filter locations by device_id.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        device_id = str(options["device_id"]).strip()

        self.stdout.write(f"database={settings.DATABASES['default']['NAME']}")
        self.stdout.write(f"devices={GpsDevice.objects.count()}")

        queryset = GpsLocation.objects.select_related("device").order_by("-created_at")
        if device_id:
            queryset = queryset.filter(device__device_id=device_id)

        total = queryset.count()
        self.stdout.write(f"locations={total}")

        rows = list(queryset[:limit])
        if not rows:
            self.stdout.write("No GPS locations found.")
            return

        for row in rows:
            payload = {
                "device_id": row.device.device_id,
                "lat": row.latitude,
                "lng": row.longitude,
                "altitude": row.altitude,
                "speed": row.speed,
                "satellites": row.satellites,
                "battery": row.battery,
                "gps_timestamp": row.gps_timestamp.isoformat(),
                "created_at": row.created_at.isoformat(),
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False))
