from django.core.management.base import BaseCommand, CommandError

from gps.mqtt_service import IMPORT_ERROR, mqtt, run_blocking_consumer


class Command(BaseCommand):
    help = "Consume GPS locations from MQTT and store them in Django."

    def handle(self, *args, **options):
        if mqtt is None:
            raise CommandError(f"paho-mqtt is not available: {IMPORT_ERROR}")
        try:
            run_blocking_consumer()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
