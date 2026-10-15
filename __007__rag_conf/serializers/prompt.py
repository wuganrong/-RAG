"""rag_conf 应用的提示词配置 Serializer。"""

from __future__ import annotations

from rest_framework import serializers


class PromptDetailSerializer(serializers.Serializer):
    """获取提示词详情的入参验证。"""

    config_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="提示词模板唯一键（与 id 二选一）",
    )
    id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="提示词配置主键（与 config_key 二选一，管理端编辑用）",
    )

    def validate(self, attrs: dict) -> dict:
        """必须提供 config_key 或 id 之一。"""
        ck = (attrs.get("config_key") or "").strip()
        pid = attrs.get("id")
        if not ck and pid is None:
            raise serializers.ValidationError("必须提供 config_key 或 id。")
        attrs["config_key"] = ck or None
        return attrs


class PromptListPageSerializer(serializers.Serializer):
    """分页查询提示词管理列表的入参验证。"""

    page = serializers.IntegerField(default=1, min_value=1, help_text="页码，从 1 开始")
    page_size = serializers.IntegerField(default=10, min_value=1, max_value=100, help_text="每页条数")
    keywords = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="按提示词名称 section_name 关键词过滤",
    )


class PromptSetSerializer(serializers.Serializer):
    """新增/更新提示词配置的入参验证。"""

    id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="主键，更新时传入",
    )
    config_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="模板唯一键",
    )
    section_name = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=255,
        help_text="提示词名称",
    )
    system_prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="系统提示词",
    )
    user_prompt_template = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="用户提示词模板",
    )
    status = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1,
        help_text="1 启用，0 禁用",
    )

    def validate_config_key(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("config_key 不能为空。")
        return value

    def validate_status(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value


class PromptDeleteSerializer(serializers.Serializer):
    """删除提示词配置的入参验证。"""

    id = serializers.IntegerField(required=True, min_value=1, help_text="提示词配置主键")
