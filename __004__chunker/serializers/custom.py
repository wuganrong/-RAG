"""chunker 应用的自定义知识块请求参数验证 Serializer。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from rest_framework import serializers


class CustomChunkListSerializer(serializers.Serializer):
    """自定义切片列表查询的入参验证。"""

    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="页码，从 1 开始")
    page_size = serializers.IntegerField(required=False, default=30, min_value=1, help_text="每页条数")
    user_name = serializers.CharField(required=False, allow_blank=True, default="", help_text="创建者姓名关键词")
    chunk_title_kwd = serializers.CharField(required=False, allow_blank=True, default="", help_text="切片标题关键词")
    available_int = serializers.IntegerField(required=False, help_text="可用状态过滤")


class CustomChunkCreateChunkSerializer(serializers.Serializer):
    """创建自定义切片的入参验证。"""

    content_with_weight = serializers.CharField(required=True, help_text="切片内容（必填）")
    chunk_title_kwd = serializers.CharField(required=True, help_text="切片标题（必填）")
    questions = serializers.ListField(required=False, default=list, help_text="关联问题列表")
    question_kwd = serializers.ListField(required=False, default=list, help_text="关联问题列表（兼容旧版字段）")
    important_kwd = serializers.ListField(required=False, default=list, help_text="关键词列表")
    available_int = serializers.IntegerField(required=False, default=1, help_text="可用状态")
    tag_kwd = serializers.ListField(required=False, default=list, help_text="标签列表")
    user_id = serializers.CharField(required=False, help_text="用户 ID")
    user_name = serializers.CharField(required=False, allow_blank=True, default="", help_text="用户名称")
    create_user_name = serializers.CharField(required=False, allow_blank=True, default="", help_text="创建者名称")


class CustomChunkSetSerializer(serializers.Serializer):
    """更新自定义切片的入参验证。"""

    chunk_id = serializers.CharField(required=True, help_text="切片 ID（必填）")
    content_with_weight = serializers.CharField(required=True, help_text="切片内容（必填）")
    important_kwd = serializers.ListField(required=False, help_text="关键词列表")
    question_kwd = serializers.ListField(required=False, help_text="问题列表")
    tag_kwd = serializers.ListField(required=False, help_text="标签列表")
    available_int = serializers.IntegerField(required=False, help_text="可用状态")
    chunk_title_kwd = serializers.CharField(required=True, help_text="切片标题（必填）")
    doc_id = serializers.CharField(required=False, allow_blank=True, help_text="关联文档 ID")
    docnm_kwd = serializers.CharField(required=False, allow_blank=True, help_text="关联文档名称")


class CustomChunkRmSerializer(serializers.Serializer):
    """删除自定义切片的入参验证。"""

    chunk_id = serializers.CharField(required=True, help_text="切片 ID（必填）")


class CustomChunkGetSerializer(serializers.Serializer):
    """获取自定义切片详情的入参验证。"""

    chunk_id = serializers.CharField(required=True, help_text="切片 ID（必填）")


class CustomChunkUpdateDocidSerializer(serializers.Serializer):
    """更新切片关联文档 ID 的入参验证。"""

    chunk_ids = serializers.ListField(required=True, help_text="切片 ID 列表（必填）")
    doc_id = serializers.CharField(required=True, help_text="文档 ID（必填）")


class CustomChunkExtractKeywordsSerializer(serializers.Serializer):
    """抽取关键词的入参验证。"""

    content = serializers.CharField(required=True, help_text="待提取关键词的文本内容（必填）")
    topn = serializers.IntegerField(required=False, default=15, help_text="提取关键词数量")


class CustomChunkExtractQuestionsSerializer(serializers.Serializer):
    """抽取问题的入参验证。"""

    content = serializers.CharField(required=True, help_text="待生成问题的文本内容（必填）")
    topn = serializers.IntegerField(required=False, default=10, help_text="生成问题数量")


class CustomChunkFileListSerializer(serializers.Serializer):
    """自定义切片文件列表的入参验证。"""

    keywords = serializers.CharField(required=False, allow_blank=True, default="", help_text="文件名关键词")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="当前页码")
    page_size = serializers.IntegerField(required=False, default=15, min_value=1, help_text="每页条数")
