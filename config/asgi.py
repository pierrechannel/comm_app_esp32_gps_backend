import os
from django.core.asgi import get_asgi_application

# Set Django settings module FIRST
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Initialize Django BEFORE importing any other Django-dependent modules
django_asgi_app = get_asgi_application()

# Now import everything else (after Django is initialized)
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from gps.mqtt_service import start_background_service
from gps.websocket_urls import websocket_urlpatterns

start_background_service(force=True)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
