from django.urls import path

from . import views


urlpatterns = [
    path("devices", views.devices_collection),
    path("devices/<str:device_key>", views.device_detail),
    path("devices/<str:device_key>/history", views.device_history),
    path("devices/<str:device_key>/history/stats", views.device_history_stats),
    path("location", views.location_ingest),
    path("locations", views.locations_collection),
    path("alerts", views.alerts_collection),
    path("alerts/read-all", views.alerts_read_all),
    path("alerts/<uuid:alert_id>", views.alert_detail),
    path("alerts/<uuid:alert_id>/read", views.alert_read),
    path("zones", views.zones_collection),
    path("zones/<uuid:zone_id>", views.zone_detail),
    path("rapports/summary", views.reports_summary),
]
