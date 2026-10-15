"""文档方法库路由。"""

from django.urls import path

from ..views import document_method

urlpatterns = [
    path("list", document_method.document_method_list),
    path("detail", document_method.document_method_detail),
    path("set", document_method.document_method_set),
    path("rm", document_method.document_method_rm),
    path("change_status", document_method.document_method_change_status),
]
