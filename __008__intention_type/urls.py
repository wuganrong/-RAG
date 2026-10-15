from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("list", views.intention_type_list),
    path("detail", views.intention_type_detail),
    path("set", views.intention_type_set),
    path("rm", views.intention_type_rm),
]
