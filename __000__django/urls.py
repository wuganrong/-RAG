"""项目 URL 配置。"""

from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from django.views.static import serve as static_serve

from __010__colpali.paths import PAGE_IMAGE_DIR


def _serve_page_images(request, filename: str):
    return static_serve(request, filename, document_root=PAGE_IMAGE_DIR)


urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="frontend"),
    path("v1/auth/", include("__015__auth.urls")),
    path("v1/kb/", include("__002__kb.urls")),
    path("v1/document/", include("__003__document.urls")),
    path("v1/chunk/", include("__004__chunker.urls.document")),
    path("v1/custom_chunk/", include("__004__chunker.urls.custom")),
    path("v1/assistant/", include("__007__rag_conf.urls.assistant")),
    path("v1/prompt/", include("__007__rag_conf.urls.prompt")),
    path("v1/retrieval/", include("__007__rag_conf.urls.retrieval")),
    path("v1/conversation/", include("__005__conversation.urls")),
    path("v1/llm/", include("__006__llm.urls")),
    path("v1/tenant/", include("__012__tenant.urls")),
    path("v1/ops/", include("__013__ops.urls")),
    path("v1/evaluation/", include("__014__evaluation.urls")),
    path("v1/intention_type/", include("__008__intention_type.urls")),
    path("v1/ner_dict/", include("__009__ner_dict.urls")),
    path("v1/document-method/", include("__007__rag_conf.urls.document_method")),
    path("v1/support-files/", include("__007__rag_conf.urls.support_file")),
    path("media/pages/<path:filename>", _serve_page_images, name="page_image"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
