"""ner_dict 应用的请求参数验证 Serializer。"""

from __future__ import annotations

from rest_framework import serializers


class NerDictListPageSerializer(serializers.Serializer):
    """分页/条件查询词典列表的入参验证。"""

    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="当前页码")
    page_size = serializers.IntegerField(required=False, default=10, min_value=1, help_text="每页条数")
    tag = serializers.CharField(required=False, allow_blank=True, help_text="类型标识(ner,dict,synonym)")
    type = serializers.CharField(required=False, allow_blank=True, help_text="细分类型(toxic,stock,firstnm)")
    dict = serializers.CharField(required=False, allow_blank=True, help_text="词典词关键词")
    status = serializers.CharField(required=False, allow_blank=True, help_text="状态(0:有效,1:无效)")
    n = serializers.CharField(required=False, allow_blank=True, help_text="词性")
    synonym = serializers.CharField(required=False, allow_blank=True, help_text="同义词")


class NerDictAddSerializer(serializers.Serializer):
    """新增词典的入参验证。"""

    dict = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100, help_text="核心词")
    tag = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20, help_text="标签类型(ner,dict,synonym)")
    type = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100, help_text="细分类型")
    synonym = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=1000, help_text="同义词列表")
    f = serializers.IntegerField(required=False, allow_null=True, help_text="词频")
    n = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=32, help_text="词性")
    remark = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255, help_text="备注")


class NerDictUpdateSerializer(serializers.Serializer):
    """更新词典的入参验证。"""

    id = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=64, help_text="词典ID")
    dict = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100, help_text="核心词")
    tag = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20, help_text="标签类型(ner,dict,synonym)")
    type = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100, help_text="细分类型")
    synonym = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=1000, help_text="同义词列表")
    f = serializers.IntegerField(required=False, allow_null=True, help_text="词频")
    n = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=32, help_text="词性")
    status = serializers.CharField(required=False, allow_blank=True, allow_null=True, help_text="状态")
    remark = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=255, help_text="备注")


class NerDictDeleteSerializer(serializers.Serializer):
    """删除词典的入参验证。"""

    id = serializers.CharField(max_length=64, help_text="词典ID（必填）")


class NerDictGetTypesSerializer(serializers.Serializer):
    """查询词典类型的入参验证。"""

    type_code = serializers.CharField(required=False, allow_blank=True, help_text="类型编码")


class NerDictRefreshSerializer(serializers.Serializer):
    """刷新词典缓存的入参验证。"""

    tag = serializers.ChoiceField(
        choices=["ner", "dict", "synonym", "replace_synonym"],
        help_text="标签类型（必填）；synonym 会同时刷新 replace_synonym 表",
    )
