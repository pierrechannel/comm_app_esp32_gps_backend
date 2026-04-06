from django.urls import path

from . import views


urlpatterns = [
    path("login", views.login_view),
    path("logout", views.logout_view),
    path("me", views.me_view),
    path("session", views.session_view),
    path("users", views.users_view),
    path("users/<uuid:user_id>", views.user_detail_view),
    path("users/<uuid:user_id>/password", views.user_password_view),
]
