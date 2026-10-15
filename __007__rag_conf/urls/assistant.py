from __future__ import annotations

from django.urls import path

from ..views import assistant

urlpatterns = [
    path("list", assistant.assistant_config_list),
    path("detail", assistant.assistant_config_detail),
    path("type_options", assistant.assistant_type_options),
    path("set", assistant.assistant_config_set),
]
