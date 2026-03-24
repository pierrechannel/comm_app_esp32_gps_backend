from __future__ import annotations

import json
import ssl

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from gps.ingest import expected_gps_api_key, ingest_location_payload

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover
    mqtt = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class Command(BaseCommand):
    help = "Consume GPS locations from MQTT and store them in Django."

    def handle(self, *args, **options):
        if mqtt is None:
            raise CommandError(f"paho-mqtt is not available: {IMPORT_ERROR}")

        expected_api_key = expected_gps_api_key()
        if not expected_api_key:
            raise CommandError("GPS_API_KEY manquant dans l'environnement.")

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.MQTT_CLIENT_ID)
        if settings.MQTT_USERNAME:
            client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD or None)
        if settings.MQTT_USE_TLS:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code != 0:
                self.stderr.write(self.style.ERROR(f"MQTT connexion echouee: {reason_code}"))
                return
            topic = settings.MQTT_TOPIC_GPS
            client.subscribe(topic)
            self.stdout.write(self.style.SUCCESS(f"MQTT connecte. Abonnement a {topic}"))

        def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
            if reason_code != 0:
                self.stderr.write(self.style.ERROR(f"MQTT deconnecte: {reason_code}"))

        def on_message(client, userdata, msg):
            try:
                body = json.loads(msg.payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self.stderr.write(self.style.ERROR(f"Payload MQTT invalide sur {msg.topic}: {exc}"))
                return

            if not isinstance(body, dict):
                self.stderr.write(self.style.ERROR(f"Payload MQTT invalide sur {msg.topic}: objet JSON attendu"))
                return

            self.stdout.write(f"[recu] {msg.topic} {json.dumps(body, ensure_ascii=False)}")

            if not body.get("device_id"):
                topic_parts = msg.topic.split("/")
                if len(topic_parts) >= 3:
                    body["device_id"] = topic_parts[2]

            response = ingest_location_payload(
                body,
                expected_api_key=expected_api_key,
                api_key=str(body.get("api_key", "")),
            )
            if response.status_code >= 400:
                self.stderr.write(
                    self.style.ERROR(
                        f"Echec ingestion MQTT sur {msg.topic}: {response.content.decode('utf-8', errors='ignore')}"
                    )
                )
                return

            self.stdout.write(
                self.style.SUCCESS(
                    f"[enregistre] {msg.topic} device={body.get('device_id')} status={response.status_code}"
                )
            )

        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        self.stdout.write(
            self.style.WARNING(
                f"MQTT connexion en cours... broker={settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT} client_id={settings.MQTT_CLIENT_ID} tls={settings.MQTT_USE_TLS}"
            )
        )
        client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
        client.loop_forever()
