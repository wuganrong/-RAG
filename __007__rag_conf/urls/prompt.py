from __future__ import annotations

from django.urls import path

from ..views import prompt

urlpatterns = [
    path("list", prompt.prompt_list),
    path("detail", prompt.prompt_detail),
    path("list_page", prompt.prompt_list_page),
    path("set", prompt.prompt_set),
    path("delete", prompt.prompt_delete),
]
