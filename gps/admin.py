from django.contrib import admin

from .models import GpsAlert, GpsDevice, GpsLocation, GpsZone, GpsZoneDevice


admin.site.register(GpsDevice)
admin.site.register(GpsLocation)
admin.site.register(GpsAlert)
admin.site.register(GpsZone)
admin.site.register(GpsZoneDevice)
