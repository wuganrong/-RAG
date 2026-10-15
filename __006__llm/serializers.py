from __future__ import annotations

from rest_framework import serializers


class LLMListQuerySerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    model_type = serializers.CharField(
        required=False,
        default="chat",
        allow_blank=True,
        help_text="模型类型过滤，默认 chat；可选 embedding、rerank 等",
    )

    def validate_model_type(self, value: str) -> str:
        v = (value or "").strip()
        return v if v else "chat"


class LLMListResponseSerializer(serializers.Serializer):
    data = serializers.DictField(help_text="按厂商分组的模型列表")


class LLMCreateSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    llm_name = serializers.CharField(max_length=128, help_text="模型名称")
    model_type = serializers.CharField(max_length=128, help_text="模型类型：chat / vlm / embedding / rerank")
    fid = serializers.CharField(max_length=128, help_text="厂商标识")
    max_tokens = serializers.IntegerField(required=False, default=0, min_value=0, help_text="最大 token 数")
    status = serializers.ChoiceField(required=False, choices=["0", "1"], default="1", help_text="状态")

    def validate_model_type(self, value: str) -> str:
        v = value.strip().lower()
        if not v:
            raise serializers.ValidationError("模型类型不能为空。")
        return v

    def validate_llm_name(self, value: str) -> str:
        v = value.strip()
        if not v:
            raise serializers.ValidationError("模型名称不能为空。")
        return v

    def validate_fid(self, value: str) -> str:
        v = value.strip()
        if not v:
            raise serializers.ValidationError("厂商标识不能为空。")
        return v


class LLMUpdateSerializer(LLMCreateSerializer):
    id = serializers.CharField(max_length=64, help_text="模型 ID")


class LLMIdSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64, help_text="模型 ID")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")


class LLMStatusSerializer(LLMIdSerializer):
    status = serializers.ChoiceField(choices=["0", "1"], help_text="状态：1 启用，0 禁用")


class LLMFactorySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, help_text="厂商名称")
    api_base = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="API Base URL")
    api_key = serializers.CharField(required=False, allow_blank=True, max_length=2048, help_text="API Key")
    status = serializers.ChoiceField(required=False, choices=["0", "1"], default="1", help_text="状态")

    def validate_name(self, value: str) -> str:
        v = value.strip()
        if not v:
            raise serializers.ValidationError("厂商名称不能为空。")
        return v
