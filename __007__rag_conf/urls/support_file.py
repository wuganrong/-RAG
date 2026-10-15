"""rag_conf 应用的支持文件管理 URL 配置。"""

from __future__ import annotations

from django.urls import path

from ..views import support_file

urlpatterns = [
    # 映射管理
    path("tree", support_file.mapping_tree),
    path("mapping/list", support_file.mapping_list),
    path("mapping/set", support_file.mapping_set),
    path("mapping/change_status", support_file.mapping_change_status),
    path("mapping/rm", support_file.mapping_rm),
    path("mapping/rename", support_file.mapping_rename),
    path("mapping/batch_bind", support_file.mapping_batch_bind),
    path("mapping/rm_by_parser", support_file.mapping_rm_by_parser),
    path("mapping/rm_by_type", support_file.mapping_rm_by_type),
    path("mapping/file_types", support_file.mapping_file_types),
    path("mapping/parsers", support_file.mapping_parsers),
    # 方法管理
    path("method/list", support_file.method_list),
    path("method/set", support_file.method_set),
    path("method/rm", support_file.method_rm),
    path("method/change_status", support_file.method_change_status),
]
