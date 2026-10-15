from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("list_page", views.ner_dict_list_page),
    path("add", views.ner_dict_add),
    path("update", views.ner_dict_update),
    path("delete", views.ner_dict_delete),
    path("getTypes", views.ner_dict_get_types),
    path("refresh", views.ner_dict_refresh),
]