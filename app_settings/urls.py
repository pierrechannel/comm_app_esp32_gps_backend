from django.urls import path

from . import views


urlpatterns = [
    path("notifications", views.notifications_view),
    path("financier", views.financial_view),
    path("etablissement", views.establishment_view),
]
