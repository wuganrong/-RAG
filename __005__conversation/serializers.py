"""conversation 应用的请求参数验证 Serializer。"""

from __future__ import annotations

from rest_framework import serializers


class ConversationGetSerializer(serializers.Serializer):
    """获取单个会话详情的入参验证（Query 参数）。"""

    conversation_id = serializers.CharField(max_length=64, help_text="会话 ID（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="用户 ID")


class ConversationListSerializer(serializers.Serializer):
    """查询会话列表的入参验证（Query 参数）。"""

    user_id = serializers.CharField(max_length=255, help_text="用户 ID（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    orderby = serializers.CharField(default="create_date", help_text="排序字段")
    desc = serializers.BooleanField(default=True, help_text="是否降序")


class ConversationSetSerializer(serializers.Serializer):
    """重命名会话的入参验证。"""

    conversation_id = serializers.CharField(max_length=64, help_text="会话 ID（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    name = serializers.CharField(max_length=255, help_text="会话标题（必填）")
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="用户 ID")


class ConversationRmSerializer(serializers.Serializer):
    """删除会话的入参验证。"""

    conversation_ids = serializers.ListField(child=serializers.CharField(max_length=64), help_text="会话 ID 列表（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="用户 ID")


class ConversationDeleteMsgSerializer(serializers.Serializer):
    """删除会话消息的入参验证。"""

    conversation_id = serializers.CharField(max_length=64, help_text="会话 ID（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    message_id = serializers.CharField(max_length=64, help_text="消息 ID（必填）")


class ConversationCompletionSerializer(serializers.Serializer):
    """对话补全的入参验证。"""

    conversation_id = serializers.CharField(max_length=64, help_text="会话 ID（必填，不存在则创建）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    messages = serializers.ListField(help_text="消息列表（必填）")
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="用户 ID（新建会话时写入）")
    name = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="会话标题（新建或更新时可选）")
    model = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="会话使用的模型（新建或更新时可选）")
    assistant_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="本次问答使用的助理 Key（如 paper 助理）；不传或传空则使用默认 chat 助理。",
    )
    kb_ids = serializers.ListField(
        required=False,
        child=serializers.CharField(max_length=64, allow_blank=False),
        help_text="本次问答使用的知识库 ID 列表；不传则使用 chat 助理默认绑定。",
    )


class ConversationCompletionWithModelSerializer(serializers.Serializer):
    """模型对比对话补全的入参验证。"""

    messages = serializers.ListField(help_text="消息列表（必填）")
    model_name = serializers.CharField(max_length=128, help_text="模型名称（必填）")
    temperature = serializers.FloatField(default=0.15, help_text="温度参数")
    top_p = serializers.FloatField(default=0.35, help_text="top_p 采样")
    enable_thinking = serializers.BooleanField(default=False, help_text="是否启用深度思考")


class ConversationCompletionWithAllSerializer(serializers.Serializer):
    """多参数对话补全的入参验证。"""

    messages = serializers.ListField(help_text="消息列表（必填）")
    system_prompt = serializers.CharField(required=False, allow_blank=True, max_length=8192, help_text="系统提示词，支持 {knowledge} 占位")
    model_name = serializers.CharField(max_length=128, help_text="模型名称（必填）")
    temperature = serializers.FloatField(default=0.5, help_text="温度参数")
    top_p = serializers.FloatField(default=0.9, help_text="top_p 采样")
    enable_thinking = serializers.BooleanField(default=False, help_text="是否启用深度思考")
    top_k = serializers.IntegerField(default=1024, help_text="检索 top_k")
    similarity_threshold = serializers.FloatField(default=0.2, help_text="相似度阈值")
    vector_similarity_weight = serializers.FloatField(default=0.3, help_text="向量相似度权重")


class ConversationFeedbackSerializer(serializers.Serializer):
    conversation_id = serializers.CharField(max_length=64, help_text="会话 ID")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    message_id = serializers.CharField(max_length=64, help_text="assistant 消息 ID")
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="用户 ID")
    rating = serializers.ChoiceField(choices=["useful", "useless"], help_text="有用 / 无用")
    reason = serializers.CharField(required=False, allow_blank=True, max_length=64, help_text="反馈原因")
    comment = serializers.CharField(required=False, allow_blank=True, help_text="反馈备注")


class ConversationFeedbackListSerializer(serializers.Serializer):
    conversation_id = serializers.CharField(required=False, allow_blank=True, max_length=64, help_text="会话 ID")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="用户 ID")


class ConversationExportSerializer(serializers.Serializer):
    conversation_id = serializers.CharField(max_length=64, help_text="会话 ID")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255, help_text="用户 ID")
    export_format = serializers.ChoiceField(required=False, choices=["json", "markdown"], default="markdown", help_text="导出格式")
