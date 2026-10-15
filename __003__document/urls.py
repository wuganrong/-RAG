from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("list", views.document_list),
    path("image/<str:image_id>", views.document_image),
    path("change_status", views.document_change_status),
    path("run", views.document_run),
    path("change_parser", views.document_change_parser),
    path("set_meta", views.document_set_meta),
    path("rename", views.document_rename),
    path("rm", views.document_rm),
    path("upload", views.document_upload),
    path("get/<str:id>", views.document_get_id),
    path("batch_download", views.document_batch_download),
    path("task/list", views.document_task_list),
    path("version/list", views.document_version_list),
]
