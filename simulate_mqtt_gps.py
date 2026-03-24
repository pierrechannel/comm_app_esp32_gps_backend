import argparse
import json
import math
import os
from pathlib import Path
import random
import ssl
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = BASE_DIR / ".env"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


def env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name, "1" if default else "0").lower()
    return value in {"1", "true", "yes", "on"}


def default_simulator_client_id() -> str:
    env_client_id = env("MQTT_SIMULATOR_CLIENT_ID", "")
    if env_client_id:
        return env_client_id
    return f"comm-app-gps-simulator-{os.getpid()}"


def parse_args() -> argparse.Namespace:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    bootstrap_args, remaining = bootstrap.parse_known_args()
    load_env_file(Path(bootstrap_args.env_file))

    parser = argparse.ArgumentParser(
        description="Publish simulated GPS locations to the MQTT broker used by the Django backend."
    )
    parser.add_argument("--env-file", default=bootstrap_args.env_file, help="Path to the .env file to load first.")
    parser.add_argument("--device-id", default="ESP32_SIM_001", help="Device id used in topic and payload.")
    parser.add_argument("--count", type=int, default=0, help="Number of messages to publish. 0 means infinite.")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between messages.")
    parser.add_argument("--lat", type=float, default=-3.3822, help="Starting latitude.")
    parser.add_argument("--lng", type=float, default=29.3644, help="Starting longitude.")
    parser.add_argument("--radius", type=float, default=0.0012, help="Path radius in degrees.")
    parser.add_argument("--speed", type=float, default=38.0, help="Average speed in km/h.")
    parser.add_argument("--battery", type=float, default=87.0, help="Starting battery percentage.")
    parser.add_argument("--satellites", type=int, default=11, help="Average satellite count.")
    parser.add_argument("--topic", default=env("MQTT_TOPIC_GPS", "gps/devices/+/location"), help="MQTT topic pattern.")
    parser.add_argument("--host", default=env("MQTT_BROKER_HOST", "127.0.0.1"), help="MQTT broker host.")
    parser.add_argument("--port", type=int, default=int(env("MQTT_BROKER_PORT", "1883")), help="MQTT broker port.")
    parser.add_argument("--username", default=env("MQTT_USERNAME", ""), help="MQTT username.")
    parser.add_argument("--password", default=env("MQTT_PASSWORD", ""), help="MQTT password.")
    parser.add_argument("--client-id", default=default_simulator_client_id(), help="MQTT client id.")
    parser.add_argument("--api-key", default=env("GPS_API_KEY", "change-me"), help="API key expected by the backend.")
    parser.add_argument("--use-tls", action="store_true", default=env_bool("MQTT_USE_TLS", False), help="Enable TLS.")
    return parser.parse_args(remaining)


def resolve_topic(pattern: str, device_id: str) -> str:
    if "+" in pattern:
        return pattern.replace("+", device_id)
    if "{device_id}" in pattern:
        return pattern.format(device_id=device_id)
    return pattern.rstrip("/") + f"/{device_id}/location"


def build_payload(args: argparse.Namespace, index: int) -> dict:
    angle = index / 8
    lat = args.lat + math.sin(angle) * args.radius + random.uniform(-0.00008, 0.00008)
    lng = args.lng + math.cos(angle) * args.radius + random.uniform(-0.00008, 0.00008)
    speed = max(0.0, args.speed + random.uniform(-7.0, 9.0))
    battery = max(5.0, min(100.0, args.battery - (index * 0.08)))
    satellites = max(3, int(round(args.satellites + random.uniform(-2, 2))))
    altitude = 780 + random.uniform(-8, 8)
    return {
        "device_id": args.device_id,
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "alt": round(altitude, 1),
        "speed": round(speed, 1),
        "satellites": satellites,
        "battery": round(battery, 1),
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        "gps_fix": True,
        "api_key": args.api_key,
    }


def main() -> int:
    args = parse_args()
    topic = resolve_topic(args.topic, args.device_id)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.client_id)
    if args.username:
        client.username_pw_set(args.username, args.password or None)
    if args.use_tls:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    connected = {"ok": False}

    def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        connected["ok"] = reason_code == 0
        if connected["ok"]:
            print(f"Connected to {args.host}:{args.port} tls={args.use_tls} client_id={args.client_id}")
            print(f"Publishing to topic: {topic}")
        else:
            print(f"MQTT connection failed with code: {reason_code}")

    def on_disconnect(client: mqtt.Client, userdata, disconnect_flags, reason_code, properties) -> None:
        connected["ok"] = False
        if reason_code != 0:
            print(f"MQTT disconnected with code: {reason_code}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()

    deadline = time.time() + 10
    while not connected["ok"] and time.time() < deadline:
        time.sleep(0.1)

    if not connected["ok"]:
        client.loop_stop()
        return 1

    sent = 0
    try:
        while args.count == 0 or sent < args.count:
            payload = build_payload(args, sent)
            data = json.dumps(payload)
            result = client.publish(topic, data, qos=0, retain=False)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"Publish failed before wait: {mqtt.error_string(result.rc)}")
                return 1
            result.wait_for_publish()
            print(f"[sent #{sent + 1}] {topic} {data}")
            sent += 1
            time.sleep(max(0.1, args.interval))
            if not connected["ok"]:
                print("MQTT connection lost. Stopping simulator.")
                return 1
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        client.loop_stop()
        client.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
