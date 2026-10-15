"""kb 应用的请求参数验证 Serializer。"""

from __future__ import annotations

from rest_framework import serializers


class KbListSerializer(serializers.Serializer):
    """分页/条件查询知识库列表的入参验证。"""

    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    page = serializers.IntegerField(default=1, min_value=1, help_text="页码，从 1 开始")
    page_size = serializers.IntegerField(default=15, min_value=0, help_text="每页条数，0 表示不分页")
    keywords = serializers.CharField(default="", allow_blank=True, help_text="关键词，模糊匹配知识库名称")
    parser_id = serializers.CharField(required=False, allow_blank=True, help_text="解析器 ID 过滤")
    orderby = serializers.CharField(default="create_date", help_text="排序字段")
    desc = serializers.BooleanField(default=True, help_text="是否降序")


_CHUNKER_CONFIG_HELP = (
    "文本切分器配置 JSON，支持以下字段：\n"
    "- auto_keywords (int)：自动抽取关键词数量，如 21\n"
    "- auto_questions (int)：自动生成问题数量，如 7\n"
    "- chunk_token_num (int)：分块 token 上限，如 512\n"
    "- delimiter (str)：分块分隔符，如 '\\\\n\\\\n'\n"
    "- mineru_max_section_chars (int)：MinerU 单节最大字符数，如 20000\n"
    "- use_macbert (bool)：是否使用 MacBERT 重排，默认 false"
)


class KbCreateSerializer(serializers.Serializer):
    """创建知识库的入参验证。"""

    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    name = serializers.CharField(max_length=128, help_text="知识库名称（必填，不可为空）")
    embd_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=128,
        help_text="向量模型 ID，如 'bge-m3@VLLM2'；不传时自动从系统配置 EMBEDDING_MODEL_ID 读取",
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="知识库描述"
    )
    permission = serializers.ChoiceField(
        choices=["me", "team"], default="me", help_text="权限：me（仅自己）/ team（团队）"
    )
    parser_id = serializers.CharField(
        required=False, allow_blank=True, max_length=32, help_text="解析器 ID，默认 naive"
    )
    chunker_id = serializers.CharField(
        required=False, allow_blank=True, max_length=32, default="naive", help_text="文本切分器 ID"
    )
    chunker_config = serializers.JSONField(required=False, default=dict, help_text=_CHUNKER_CONFIG_HELP)
    avatar = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="头像（base64 字符串）"
    )
    rag_mode = serializers.ChoiceField(
        choices=["text", "vision", "hybrid"], default="vision", required=False,
        help_text="检索模式：text / vision / hybrid",
    )
    vlm_id = serializers.CharField(required=False, allow_blank=True, default="qwen-vl-plus")
    page_top_n = serializers.IntegerField(required=False, default=3, min_value=1, max_value=12)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("知识库名称不能为空。")
        return value


class KbRmSerializer(serializers.Serializer):
    """删除知识库的入参验证。"""

    kb_id = serializers.CharField(max_length=64, help_text="知识库 ID（必填）")


class KbDetailSerializer(serializers.Serializer):
    """获取知识库详情的入参验证（Query 参数）。"""

    kb_id = serializers.CharField(max_length=64, help_text="知识库 ID（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")


class KbUpdateSerializer(serializers.Serializer):
    """更新知识库的入参验证。"""

    kb_id = serializers.CharField(max_length=64, help_text="知识库 ID（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    name = serializers.CharField(max_length=128, help_text="知识库名称（必填）")
    embd_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=128,
        help_text="向量模型 ID，如 'bge-m3@VLLM2'；不传则保持原值不变",
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="知识库描述"
    )
    parser_id = serializers.CharField(max_length=32, help_text="解析器 ID（必填）")
    permission = serializers.ChoiceField(
        choices=["me", "team"], required=False, help_text="权限"
    )
    chunker_id = serializers.CharField(
        required=False, allow_blank=True, max_length=32, help_text="文本切分器 ID"
    )
    chunker_config = serializers.JSONField(required=False, help_text=_CHUNKER_CONFIG_HELP)
    avatar = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="头像（base64 字符串）"
    )
    rag_mode = serializers.ChoiceField(
        choices=["text", "vision", "hybrid"], required=False,
        help_text="检索模式：text / vision / hybrid",
    )
    vlm_id = serializers.CharField(required=False, allow_blank=True)
    page_top_n = serializers.IntegerField(required=False, min_value=1, max_value=12)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("知识库名称不能为空。")
        return value


class KbTagsSerializer(serializers.Serializer):
    """查询知识库标签的入参验证（Query 参数）。"""

    kb_ids = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="知识库 ID 列表，逗号分隔，如 'id1,id2'"
    )


class KbAclListSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64)
    kb_id = serializers.CharField(max_length=64)


class KbAclSaveSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64)
    kb_id = serializers.CharField(max_length=64)
    subject_type = serializers.ChoiceField(choices=["user", "role"])
    subject_id = serializers.CharField(max_length=255)
    permission = serializers.ChoiceField(choices=["read", "write", "admin"], default="read")
    status = serializers.ChoiceField(required=False, choices=["0", "1"], default="1")


class KbAclRmSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64)
    id = serializers.CharField(max_length=64)
