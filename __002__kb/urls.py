from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("list", views.kb_list),
    path("create", views.kb_create),
    path("rm", views.kb_rm),
    path("detail", views.kb_detail),
    path("update", views.kb_update),
    path("tags", views.kb_tags),
    path("acl/list", views.kb_acl_list),
    path("acl/save", views.kb_acl_save),
    path("acl/rm", views.kb_acl_rm),
]
