from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("get", views.conversation_get),
    path("list", views.conversation_list),
    path("set", views.conversation_set),
    path("rm", views.conversation_rm),
    path("export", views.conversation_export),
    path("delete_msg", views.conversation_delete_msg),
    path("feedback", views.conversation_feedback),
    path("feedback/list", views.conversation_feedback_list),
    path("completion", views.conversation_completion),
    path("completion_with_model", views.conversation_completion_with_model),
    path("completion_with_all", views.conversation_completion_with_all),
]
