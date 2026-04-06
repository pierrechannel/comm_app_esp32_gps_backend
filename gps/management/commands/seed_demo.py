from __future__ import annotations

from datetime import timedelta
from math import sin

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import AppUser, AuditLog
from app_settings.models import EstablishmentSettings, FinancialSettings, NotificationSettings
from gps.models import GpsAlert, GpsDevice, GpsLocation, GpsZone, GpsZoneDevice


ADMIN_EMAIL = "admin@gps.local"
ADMIN_PASSWORD = "admin123"
MANAGER_EMAIL = "manager@gps.local"
MANAGER_PASSWORD = "manager123"


class Command(BaseCommand):
    help = "Seed demo users, settings, GPS devices, locations, alerts, and zones."

    def handle(self, *args, **options):
        with transaction.atomic():
            self._seed_users()
            self._seed_settings()
            devices = self._seed_devices_and_locations()
            self._seed_zones(devices)
            self._seed_alerts(devices)
            self._seed_audit_logs()

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write(f"Login admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        self.stdout.write(f"Login manager: {MANAGER_EMAIL} / {MANAGER_PASSWORD}")

    def _seed_users(self) -> None:
        users = [
            {
                "email": ADMIN_EMAIL,
                "defaults": {
                    "name": "Admin Principal",
                    "role": "ADMIN",
                    "active": True,
                    "password_hash": make_password(ADMIN_PASSWORD),
                },
            },
            {
                "email": MANAGER_EMAIL,
                "defaults": {
                    "name": "Responsable GPS",
                    "role": "OPERATEUR",
                    "active": True,
                    "password_hash": make_password(MANAGER_PASSWORD),
                },
            },
        ]
        for row in users:
            AppUser.objects.update_or_create(email=row["email"], defaults=row["defaults"])

    def _seed_settings(self) -> None:
        NotificationSettings.objects.update_or_create(
            id=1,
            defaults={
                "stock_low_alert": True,
                "checkout_reminder": True,
                "missing_cash_close": True,
                "daily_auto_summary": True,
            },
        )
        FinancialSettings.objects.update_or_create(
            id=1,
            defaults={
                "currency": "BIF",
                "tax_rate": 18,
                "fiscal_year_start": "01",
            },
        )
        EstablishmentSettings.objects.update_or_create(
            id=1,
            defaults={
                "establishment_name": "Comm App GPS Demo",
                "address": "Boulevard de l'Uprona, Bujumbura",
                "phone": "+257 79 000 000",
                "email": "contact@hotel.local",
                "city": "Bujumbura",
                "country": "Burundi",
                "logo_url": "",
            },
        )

    def _seed_devices_and_locations(self) -> dict[str, GpsDevice]:
        specs = [
            {
                "device_id": "ESP32_001",
                "name": "Vehicule Direction",
                "description": "Traceur de demonstration pour le vehicule principal.",
                "origin_lat": -3.3822,
                "origin_lng": 29.3644,
                "speed_base": 42,
                "battery_base": 81,
            },
            {
                "device_id": "ESP32_002",
                "name": "Vehicule Livraison",
                "description": "Traceur de demonstration pour les tournees de livraison.",
                "origin_lat": -3.375,
                "origin_lng": 29.359,
                "speed_base": 36,
                "battery_base": 64,
            },
            {
                "device_id": "ESP32_003",
                "name": "Moto Support",
                "description": "Traceur de demonstration pour les interventions rapides.",
                "origin_lat": -3.39,
                "origin_lng": 29.372,
                "speed_base": 55,
                "battery_base": 28,
            },
        ]

        devices: dict[str, GpsDevice] = {}
        now = timezone.now()

        for index, spec in enumerate(specs):
            device, _ = GpsDevice.objects.update_or_create(
                device_id=spec["device_id"],
                defaults={
                    "name": spec["name"],
                    "description": spec["description"],
                    "active": True,
                },
            )
            devices[spec["device_id"]] = device

            if device.locations.exists():
                continue

            rows: list[GpsLocation] = []
            for step in range(36):
                angle = (step + 1 + index * 3) / 6
                rows.append(
                    GpsLocation(
                        device=device,
                        latitude=spec["origin_lat"] + 0.01 * sin(angle) + (index * 0.002),
                        longitude=spec["origin_lng"] + 0.012 * sin(angle / 1.7),
                        altitude=780 + step,
                        speed=max(0, spec["speed_base"] + 12 * sin(angle * 1.3)),
                        satellites=9 + ((step + index) % 4),
                        battery=max(9, spec["battery_base"] - step * 0.8),
                        gps_timestamp=now - timedelta(hours=18 - (step * 0.4)),
                    )
                )
            GpsLocation.objects.bulk_create(rows)

        return devices

    def _seed_zones(self, devices: dict[str, GpsDevice]) -> None:
        city_zone, _ = GpsZone.objects.update_or_create(
            name="Centre Bujumbura",
            defaults={
                "zone_type": "AUTORISEE",
                "latitude": -3.3822,
                "longitude": 29.3644,
                "radius": 2200,
                "shape_type": "CIRCLE",
                "polygon": [],
                "active": True,
                "color": "#10B981",
            },
        )
        fuel_zone, _ = GpsZone.objects.update_or_create(
            name="Depot Sensible",
            defaults={
                "zone_type": "INTERDITE",
                "latitude": -3.4015,
                "longitude": 29.349,
                "radius": 500,
                "shape_type": "CIRCLE",
                "polygon": [],
                "active": True,
                "color": "#EF4444",
            },
        )

        for zone in (city_zone, fuel_zone):
            zone.devices.clear()
            GpsZoneDevice.objects.bulk_create(
                [GpsZoneDevice(zone=zone, device=device) for device in devices.values()],
                ignore_conflicts=True,
            )

    def _seed_alerts(self, devices: dict[str, GpsDevice]) -> None:
        if GpsAlert.objects.exists():
            return

        now = timezone.now()
        alerts = [
            GpsAlert(
                device=devices["ESP32_001"],
                alert_type="SPEEDING",
                message="Vitesse excessive detectee sur l'avenue du Port.",
                latitude=-3.378,
                longitude=29.367,
                created_at=now - timedelta(hours=5),
            ),
            GpsAlert(
                device=devices["ESP32_002"],
                alert_type="OUT_OF_ZONE",
                message="Sortie zone autorisee: Centre Bujumbura",
                latitude=-3.41,
                longitude=29.341,
                created_at=now - timedelta(hours=3),
            ),
            GpsAlert(
                device=devices["ESP32_003"],
                alert_type="LOW_BATTERY",
                message="Batterie faible.",
                latitude=-3.394,
                longitude=29.376,
                created_at=now - timedelta(minutes=90),
            ),
            GpsAlert(
                device=devices["ESP32_003"],
                alert_type="SIGNAL_LOST",
                message="Signal GPS instable detecte.",
                latitude=-3.392,
                longitude=29.374,
                is_read=True,
                created_at=now - timedelta(minutes=30),
            ),
        ]
        GpsAlert.objects.bulk_create(alerts)

    def _seed_audit_logs(self) -> None:
        if AuditLog.objects.exists():
            return

        admin = AppUser.objects.filter(email=ADMIN_EMAIL).first()
        if admin is None:
            return

        now = timezone.now()
        AuditLog.objects.bulk_create(
            [
                AuditLog(
                    user_id_value=str(admin.id),
                    user_name=admin.name,
                    user_role=admin.role,
                    action="LOGIN",
                    entity="Session",
                    entity_id_value=str(admin.id),
                    description="Connexion utilisateur: Admin Principal.",
                    created_at=now - timedelta(hours=6),
                ),
                AuditLog(
                    user_id_value=str(admin.id),
                    user_name=admin.name,
                    user_role=admin.role,
                    action="CREATE",
                    entity="GpsDevice",
                    description="Initialisation des appareils de demonstration.",
                    created_at=now - timedelta(hours=5, minutes=45),
                ),
                AuditLog(
                    user_id_value=str(admin.id),
                    user_name=admin.name,
                    user_role=admin.role,
                    action="UPDATE",
                    entity="Parametres",
                    description="Initialisation des parametres de demonstration.",
                    created_at=now - timedelta(hours=5, minutes=30),
                ),
            ]
        )
