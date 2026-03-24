from django.urls import path

from .consumers import GpsLiveConsumer


websocket_urlpatterns = [
    path("ws/gps/live/", GpsLiveConsumer.as_asgi()),
]
