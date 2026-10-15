from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("login", views.login),
    path("me", views.me),
    path("logout", views.logout),
]
