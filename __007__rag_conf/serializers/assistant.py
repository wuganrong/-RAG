"""rag_conf 应用的助理配置 Serializer。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from rest_framework import serializers


class AssistantConfigListSerializer(serializers.Serializer):
    """分页/条件查询助理配置列表的入参验证。"""

    page = serializers.IntegerField(default=1, min_value=1, help_text="页码，从 1 开始")
    page_size = serializers.IntegerField(default=10, min_value=1, max_value=100, help_text="每页条数，最大 100")
    keywords = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="关键词，按助理类型和提示词名称模糊搜索",
    )


class AssistantConfigDetailSerializer(serializers.Serializer):
    """获取助理配置详情的入参验证。"""

    id = serializers.CharField(required=True, max_length=64, help_text="助理配置 ID")

    def validate_id(self, value: str) -> str:
        """校验助理配置 ID 不能为空。"""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("助理配置 ID 不能为空。")
        return value


class AssistantConfigSetSerializer(serializers.Serializer):
    """新增/更新助理配置的入参验证。"""

    id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=64,
        help_text="助理配置 ID，更新时传入",
    )
    assistant_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="业务唯一标识，如 chat、customer_service",
    )
    assistant_type = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=16,
        help_text="conversation（对话）或 task（任务）",
    )
    assistant_name = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=128,
        help_text="助理名称",
    )
    prompt_config_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="关联提示词模板 Key",
    )
    model_name = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=128,
        help_text="模型名称",
    )
    llm_setting = serializers.JSONField(required=False, help_text="LLM 参数 JSON")
    max_tokens = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="最大 token 数",
    )
    extra_params = serializers.JSONField(required=False, help_text="其他 create 参数 JSON")
    retrieval_method = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=32,
        help_text="检索方法标识",
    )
    similarity_threshold = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=1,
        help_text="相似度阈值，范围 0-1",
    )
    vector_similarity_weight = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=1,
        help_text="向量相似度权重，范围 0-1",
    )
    top_n = serializers.IntegerField(required=False, min_value=0, help_text="召回向量数量")
    rerank_id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=128,
        help_text="重排模型 ID",
    )
    kb_ids = serializers.ListField(
        required=False,
        child=serializers.CharField(max_length=64, allow_blank=False),
        help_text="关联知识库 ID 列表",
    )
    memory_rounds = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="多轮对话记忆轮数",
    )
    top_k = serializers.IntegerField(required=False, min_value=0, help_text="生成 Top_K 参数")
    prologue = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="对话开场白",
    )
    status = serializers.CharField(
        required=False,
        max_length=1,
        help_text="状态，1:启用，0:禁用",
    )

    _ASSISTANT_TYPE_ALLOWED = frozenset({"conversation", "task"})

    def validate_assistant_key(self, value: str) -> str:
        """校验助理唯一键不能为空。"""
        return self._validate_optional_non_blank(value, "assistant_key 不能为空。")

    def validate_assistant_name(self, value: str | None) -> str | None:
        """去掉首尾空格；空字符串视为未命名。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def validate_assistant_type(self, value: str) -> str:
        """校验助理类型为对话或任务。"""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("assistant_type 不能为空。")
        if value not in self._ASSISTANT_TYPE_ALLOWED:
            raise serializers.ValidationError(
                "assistant_type 只能为 conversation（对话）或 task（任务）。"
            )
        return value

    def validate_prompt_config_key(self, value: str) -> str:
        """校验提示词模板 Key 不能为空。"""
        return self._validate_optional_non_blank(value, "prompt_config_key 不能为空。")

    def validate_llm_setting(self, value: Any) -> dict[str, Any]:
        """校验 LLM 参数必须为 JSON 对象。"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("llm_setting 必须是 JSON 对象。")
        return value

    def validate_extra_params(self, value: Any) -> dict[str, Any]:
        """校验额外参数必须为 JSON 对象。"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("extra_params 必须是 JSON 对象。")
        return value

    def validate_status(self, value: str) -> str:
        """校验状态值。"""
        if value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value

    @staticmethod
    def _validate_optional_non_blank(value: str, message: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError(message)
        return value
