from __future__ import annotations

from django.apps import AppConfig


class ChunkerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "__004__chunker"
    label = "chunker"
