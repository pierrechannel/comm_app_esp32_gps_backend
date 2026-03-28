from __future__ import annotations

import json
import logging
import os
import ssl
import sys
import threading
import time
from pathlib import Path

from django.conf import settings

from gps.ingest import expected_gps_api_key, ingest_location_payload

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent
OUT_LOG = BASE_DIR / "consumer.out.log"
ERR_LOG = BASE_DIR / "consumer.err.log"

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover
    mqtt = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def configure_service_logging() -> None:
    if getattr(configure_service_logging, "_configured", False):
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    info_handler = logging.FileHandler(OUT_LOG, encoding="utf-8")
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    info_handler.setFormatter(formatter)

    error_handler = logging.FileHandler(ERR_LOG, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.addHandler(info_handler)
    logger.addHandler(error_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False

    configure_service_logging._configured = True


def should_autostart_service() -> bool:
    if not getattr(settings, "GPS_AUTO_START_MQTT_CONSUMER", False):
        return False

    if os.environ.get("GPS_MQTT_SERVICE_STARTED") == "1":
        return False

    argv = {arg.lower() for arg in sys.argv}
    is_server_process = bool({"runserver", "daphne", "uvicorn", "gunicorn"} & argv)
    if not is_server_process:
        return False

    if "runserver" in argv and os.environ.get("RUN_MAIN") != "true":
        return False

    return True


def run_blocking_consumer() -> None:
    configure_service_logging()

    if mqtt is None:
        raise RuntimeError(f"paho-mqtt is not available: {IMPORT_ERROR}")

    expected_api_key = expected_gps_api_key()
    if not expected_api_key:
        raise RuntimeError("GPS_API_KEY manquant dans l'environnement.")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.MQTT_CLIENT_ID)
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD or None)
    if settings.MQTT_USE_TLS:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            logger.error("MQTT connexion echouee: %s", reason_code)
            return
        topic = settings.MQTT_TOPIC_GPS
        client.subscribe(topic)
        logger.info("MQTT connecte. Abonnement a %s", topic)

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        if reason_code != 0:
            logger.error("MQTT deconnecte: %s", reason_code)

    def on_message(client, userdata, msg):
        try:
            body = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.error("Payload MQTT invalide sur %s: %s", msg.topic, exc)
            return

        if not isinstance(body, dict):
            logger.error("Payload MQTT invalide sur %s: objet JSON attendu", msg.topic)
            return

        logger.info("[recu] %s %s", msg.topic, json.dumps(body, ensure_ascii=False))

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
            logger.error(
                "Echec ingestion MQTT sur %s: %s",
                msg.topic,
                response.content.decode("utf-8", errors="ignore"),
            )
            return

        logger.info("[enregistre] %s device=%s status=%s", msg.topic, body.get("device_id"), response.status_code)

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    logger.warning(
        "MQTT connexion en cours... broker=%s:%s client_id=%s tls=%s",
        settings.MQTT_BROKER_HOST,
        settings.MQTT_BROKER_PORT,
        settings.MQTT_CLIENT_ID,
        settings.MQTT_USE_TLS,
    )
    client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    client.loop_forever()


def start_background_service() -> None:
    if not should_autostart_service():
        return

    configure_service_logging()
    os.environ["GPS_MQTT_SERVICE_STARTED"] = "1"

    def runner() -> None:
        while True:
            try:
                run_blocking_consumer()
            except Exception:
                logger.exception("Le service MQTT GPS a echoue. Nouvelle tentative dans 5 secondes.")
                time.sleep(5)

    thread = threading.Thread(target=runner, name="gps-mqtt-service", daemon=True)
    thread.start()
    logger.warning("Service MQTT GPS demarre depuis gps.apps.")
