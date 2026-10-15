from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("list", views.llm_list, name="llm-list"),
    path("create", views.llm_create, name="llm-create"),
    path("update", views.llm_update, name="llm-update"),
    path("rm", views.llm_rm, name="llm-rm"),
    path("set_status", views.llm_set_status, name="llm-set-status"),
    path("test", views.llm_test, name="llm-test"),
    path("factory/list", views.llm_factory_list, name="llm-factory-list"),
    path("factory/set", views.llm_factory_set, name="llm-factory-set"),
    path("factory/rotation/list", views.llm_factory_rotation_list, name="llm-factory-rotation-list"),
]
