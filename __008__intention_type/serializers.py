"""intention_type 应用的请求参数验证 Serializer。"""

from __future__ import annotations

from rest_framework import serializers


class IntentionTypeListSerializer(serializers.Serializer):
    """意图类型树形列表查询入参验证（可选状态过滤）。"""

    status = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="状态过滤，1:有效，0:无效，空表示全部",
    )


class IntentionTypeDetailSerializer(serializers.Serializer):
    """获取单个意图类型详情的入参验证。"""

    id = serializers.IntegerField(required=True, help_text="意图类型 ID（必填）")

    def validate_id(self, value: int) -> int:
        if value <= 0:
            raise serializers.ValidationError("id 必须为正整数。")
        return value


class IntentionTypeSetSerializer(serializers.Serializer):
    """新增或更新意图类型的入参验证（与 rag.models.IntentionType 全字段对齐）。"""

    id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="意图类型 ID（更新时传入，新增时不传）",
    )
    intention = serializers.CharField(
        max_length=30,
        help_text="意图名称（必填）",
    )
    intention_description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="意图描述说明",
    )
    parent_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="父意图 ID，根节点不传或传 null",
    )
    intent_type = serializers.ChoiceField(
        choices=[("C", "分类节点"), ("T", "任务节点")],
        default="T",
        help_text="意图类型：C=分类节点（仅路由），T=任务节点（触发执行）",
    )
    status = serializers.ChoiceField(
        choices=[("1", "有效"), ("0", "无效")],
        default="1",
        help_text="状态，1:有效，0:无效",
    )
    is_default = serializers.ChoiceField(
        choices=[("1", "是"), ("0", "否")],
        default="0",
        help_text="是否为默认意图，1:是，0:否",
    )
    kb_ids = serializers.ListField(
        required=False,
        default=list,
        child=serializers.CharField(max_length=64, allow_blank=False),
        help_text="关联知识库 ID 列表",
    )
    sys_prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        default="",
        help_text="系统提示词",
    )
    inherit_slots = serializers.BooleanField(
        required=False,
        default=False,
        help_text="是否自动继承所有父级意图已定义的槽位",
    )
    child_match_policy = serializers.ChoiceField(
        choices=[("F", "全执行"), ("C", "条件分支"), ("L", "LLM判别")],
        default="L",
        help_text="子意图匹配策略：F=全执行，C=条件分支，L=LLM判别",
    )
    is_fallback = serializers.BooleanField(
        required=False,
        default=False,
        help_text="是否为兜底意图（同层级中仅一个可为 True）",
    )

    def validate_intention(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("意图名称不能为空。")
        return value

    def validate_parent_id(self, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise serializers.ValidationError("parent_id 必须为正整数。")
        return value

    def validate_id(self, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise serializers.ValidationError("id 必须为正整数。")
        return value


class IntentionTypeRmSerializer(serializers.Serializer):
    """删除意图类型的入参验证。"""

    id = serializers.IntegerField(required=True, help_text="意图类型 ID（必填）")

    def validate_id(self, value: int) -> int:
        if value <= 0:
            raise serializers.ValidationError("id 必须为正整数。")
        return value
