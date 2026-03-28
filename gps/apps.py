from django.apps import AppConfig


class GpsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gps"

    def ready(self) -> None:
        from .mqtt_service import start_background_service

        start_background_service()
