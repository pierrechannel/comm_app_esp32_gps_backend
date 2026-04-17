from __future__ import annotations

import uuid

from django.db import models


class GpsDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=191)
    description = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.device_id})"


class GpsLocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(GpsDevice, related_name="locations", on_delete=models.CASCADE)
    latitude = models.FloatField()
    longitude = models.FloatField()
    altitude = models.FloatField(blank=True, null=True)
    speed = models.FloatField(blank=True, null=True)
    satellites = models.IntegerField(blank=True, null=True)
    battery = models.FloatField(blank=True, null=True)
    heart_rate = models.FloatField(blank=True, null=True)
    pulse_raw = models.IntegerField(blank=True, null=True)
    pulse_ok = models.BooleanField(blank=True, null=True)
    gps_timestamp = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-gps_timestamp"]
        indexes = [
            models.Index(fields=["device", "gps_timestamp"]),
        ]


class GpsAlert(models.Model):
    ALERT_TYPES = [
        ("SPEEDING", "Speeding"),
        ("LOW_BATTERY", "Low battery"),
        ("SIGNAL_LOST", "Signal lost"),
        ("OUT_OF_ZONE", "Out of zone"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(GpsDevice, related_name="alerts", on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=40, choices=ALERT_TYPES)
    message = models.TextField()
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class GpsZone(models.Model):
    ZONE_TYPES = [
        ("AUTORISEE", "Autorisee"),
        ("INTERDITE", "Interdite"),
    ]
    SHAPE_TYPES = [
        ("CIRCLE", "Circle"),
        ("POLYGON", "Polygon"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=191)
    zone_type = models.CharField(max_length=20, choices=ZONE_TYPES)
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius = models.FloatField()
    shape_type = models.CharField(max_length=20, choices=SHAPE_TYPES, default="CIRCLE")
    polygon = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    color = models.CharField(max_length=32, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    devices = models.ManyToManyField(GpsDevice, through="GpsZoneDevice", related_name="zone_links")

    class Meta:
        ordering = ["-created_at"]


class GpsZoneDevice(models.Model):
    zone = models.ForeignKey(GpsZone, on_delete=models.CASCADE)
    device = models.ForeignKey(GpsDevice, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("zone", "device")
