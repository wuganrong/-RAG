from __future__ import annotations

from django.urls import path

from ..views import document

urlpatterns = [
    path("methods", document.chunk_methods),
    path("list", document.chunk_list),
    path("switch", document.chunk_switch),
    path("rm", document.chunk_rm),
    path("create", document.chunk_create),
    path("get", document.chunk_get),
    path("set", document.chunk_set),
    path("retrieval_test", document.chunk_retrieval_test),
    path("retrieval_chunks", document.chunk_retrieval_chunks),
]
