from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class AppUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=191)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(max_length=64, default="ADMIN")
    active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    ACTIONS = [
        ("CREATE", "Create"),
        ("UPDATE", "Update"),
        ("DELETE", "Delete"),
        ("LOGIN", "Login"),
        ("LOGOUT", "Logout"),
        ("EXPORT", "Export"),
        ("CAISSE_CLOSE", "Caisse close"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id_value = models.CharField(max_length=64)
    user_name = models.CharField(max_length=191)
    user_role = models.CharField(max_length=64)
    action = models.CharField(max_length=32, choices=ACTIONS)
    entity = models.CharField(max_length=64)
    entity_id_value = models.CharField(max_length=64, blank=True, null=True)
    description = models.TextField()
    ip_address = models.CharField(max_length=64, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
