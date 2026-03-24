# Backend Django

Ce dossier ajoute un backend Django pour le module GPS du projet.

## Installation

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations gps
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 0.0.0.0:8000
```

## Comptes de demonstration

Apres `python manage.py seed_demo`, vous pouvez vous connecter avec:

```text
admin@hotel.local / admin123
manager@hotel.local / manager123
```

## Variables d'environnement

```env
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_CORS_ALLOW_ALL=1
DJANGO_TIME_ZONE=Africa/Bujumbura
GPS_API_KEY=change-me
MQTT_BROKER_HOST=YOUR_CLUSTER.s1.eu.hivemq.cloud
MQTT_BROKER_PORT=8883
MQTT_USERNAME=YOUR_HIVEMQ_USERNAME
MQTT_PASSWORD=YOUR_HIVEMQ_PASSWORD
MQTT_CLIENT_ID=comm-app-gps-backend
MQTT_TOPIC_GPS=gps/devices/+/location
```

Exemple HiveMQ Cloud:

```env
MQTT_BROKER_HOST=xxxxxxxx.s1.eu.hivemq.cloud
MQTT_BROKER_PORT=8883
MQTT_USERNAME=xxxxxxxx
MQTT_PASSWORD=xxxxxxxx
```

Pour utiliser une base MySQL avec Django:

```env
DJANGO_DB_ENGINE=django.db.backends.mysql
DJANGO_DB_NAME=comm_app
DJANGO_DB_USER=root
DJANGO_DB_PASSWORD=secret
DJANGO_DB_HOST=127.0.0.1
DJANGO_DB_PORT=3306
```

## Integration frontend

Dans la racine du projet Next.js, ajoute:

```env
DJANGO_BACKEND_URL=http://127.0.0.1:8000
```

Avec cette variable, Next.js proxy automatiquement toutes les routes `/api/gps/*` vers Django.

## Ingestion MQTT

Le backend peut aussi consommer les positions GPS depuis MQTT:

```bash
python manage.py consume_gps_mqtt
```

Le payload MQTT attendu est le meme JSON que l'ancien `POST /api/gps/location`, par exemple:

```json
{
  "device_id": "ESP32_002",
  "lat": -3.3822,
  "lng": 29.3644,
  "alt": 780,
  "speed": 42.5,
  "satellites": 10,
  "battery": 64,
  "timestamp": 1719999999000,
  "gps_fix": true,
  "api_key": "change-me"
}
```

## Perimetre migre

- `GET/POST /api/gps/devices`
- `GET/PUT/DELETE /api/gps/devices/<deviceId>`
- `GET /api/gps/devices/<deviceId>/history`
- `GET /api/gps/devices/<deviceId>/history/stats`
- `POST /api/gps/location`
- `GET /api/gps/locations`
- `GET /api/gps/alerts`
- `PUT /api/gps/alerts/read-all`
- `PUT /api/gps/alerts/<id>/read`
- `DELETE /api/gps/alerts/<id>`
- `GET/POST /api/gps/zones`
- `PUT/DELETE /api/gps/zones/<id>`
- `GET /api/gps/rapports/summary`
