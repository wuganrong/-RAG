from __future__ import annotations

from django.urls import path

from ..views import custom

urlpatterns = [
    path("list", custom.custom_chunk_list),
    path("rm", custom.custom_chunk_rm),
    path("upload", custom.custom_chunk_upload),
    path("update_docid", custom.custom_chunk_update_docid),
    path("extract_keywords", custom.custom_chunk_extract_keywords),
    path("extract_questions", custom.custom_chunk_extract_questions),
    path("get", custom.custom_chunk_get),
    path("create_chunk", custom.custom_chunk_create_chunk),
    path("set", custom.custom_chunk_set),
    path("file_list", custom.custom_chunk_file_list),
]
