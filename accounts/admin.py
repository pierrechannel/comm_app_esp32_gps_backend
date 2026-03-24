from django.contrib import admin

from .models import AppUser, AuditLog


admin.site.register(AppUser)
admin.site.register(AuditLog)
