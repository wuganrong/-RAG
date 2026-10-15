"""文档方法库（document_method_config）Serializer。"""

from __future__ import annotations

from rest_framework import serializers


class DocumentMethodListSerializer(serializers.Serializer):
    """方法库列表查询入参。"""

    method_type = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=16,
        help_text="方法类型过滤：parser / chunker",
    )
    keywords = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="关键词，模糊匹配 method / display_name / method_class",
    )

    def validate_method_type(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"parser", "chunker"}:
            raise serializers.ValidationError("method_type 只能为 parser 或 chunker。")
        return value


class DocumentMethodSetSerializer(serializers.Serializer):
    """新增/更新方法的入参验证。"""

    method = serializers.CharField(required=True, max_length=32, help_text="方法标识")
    method_type = serializers.CharField(required=True, max_length=16, help_text="parser / chunker")
    display_name = serializers.CharField(required=True, max_length=128, help_text="前端显示名称")
    method_class = serializers.CharField(required=True, max_length=255, help_text="方法类完整导入路径")
    status = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1,
        help_text="1 启用，0 禁用",
    )
    config_schema = serializers.JSONField(
        required=False,
        default=list,
        help_text="动态表单 Schema（JSON 数组）",
    )
    original_method = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=32,
        help_text="更新时传入原 method 值，用于定位记录",
    )

    def validate_method(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("方法标识不能为空。")
        return value

    def validate_method_type(self, value: str) -> str:
        value = value.strip()
        if value not in {"parser", "chunker"}:
            raise serializers.ValidationError("method_type 只能为 parser 或 chunker。")
        return value

    def validate_display_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("显示名称不能为空。")
        return value

    def validate_method_class(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("方法类路径不能为空。")
        return value

    def validate_status(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value


class DocumentMethodDeleteSerializer(serializers.Serializer):
    """删除方法的入参验证。"""

    method = serializers.CharField(required=True, max_length=32, help_text="方法标识")
    method_type = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=16,
        help_text="方法类型，可选，用于精确匹配",
    )

    def validate_method(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("方法标识不能为空。")
        return value

    def validate_method_type(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"parser", "chunker"}:
            raise serializers.ValidationError("method_type 只能为 parser 或 chunker。")
        return value


class DocumentMethodChangeStatusSerializer(serializers.Serializer):
    """切换方法状态的入参验证。"""

    method = serializers.CharField(required=True, max_length=32, help_text="方法标识")
    status = serializers.CharField(required=True, max_length=1, help_text="1 启用，0 禁用")
    method_type = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=16,
        help_text="方法类型，可选，用于精确匹配",
    )

    def validate_method(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("方法标识不能为空。")
        return value

    def validate_status(self, value: str) -> str:
        value = value.strip()
        if value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value

    def validate_method_type(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"parser", "chunker"}:
            raise serializers.ValidationError("method_type 只能为 parser 或 chunker。")
        return value
