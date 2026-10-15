from __future__ import annotations

from django.urls import path

from ..views import retrieval

urlpatterns = [
    path("list", retrieval.retrieval_method_list),
    path("strategy/get", retrieval.retrieval_strategy_get),
    path("strategy/save", retrieval.retrieval_strategy_save),
    path("debug", retrieval.retrieval_debug),
    path("compare", retrieval.retrieval_compare),
]
