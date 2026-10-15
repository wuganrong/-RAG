"""document 应用的请求入参验证 Serializer。"""

from __future__ import annotations

# 1. Python 标准库
import json

# 2. 第三方库
from rest_framework import serializers


class DocListSerializer(serializers.Serializer):
    """GET /document/list 入参验证。"""

    kb_id = serializers.CharField(max_length=256, help_text="所属知识库 ID（必填）")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    keywords = serializers.CharField(
        required=False, default="", allow_blank=True,
        help_text="文件名关键词，模糊匹配",
    )
    page = serializers.IntegerField(default=1, min_value=1, help_text="页码，从 1 开始")
    page_size = serializers.IntegerField(
        default=15, min_value=1, help_text="每页条数，默认 15",
    )
    orderby = serializers.CharField(
        default="create_date", allow_blank=True,
        help_text="排序字段，默认 create_date",
    )
    desc = serializers.BooleanField(default=True, help_text="是否降序，默认 true")
    status = serializers.CharField(
        required=False, default="", allow_blank=True,
        help_text="启用状态过滤，如 '0'=未启用，'1'=启用，不传则不过滤",
    )
    run = serializers.CharField(
        required=False, default="", allow_blank=True,
        help_text="解析运行状态过滤，如 '0'/'1'/'2'/'3'/'-1'；支持逗号分隔多值，如 '0,2'",
    )

    _VALID_RUN = ("0", "1", "2", "3", "-1")

    def validate_status(self, value: str) -> str:
        value = str(value).strip()
        if not value:
            return ""
        if value not in ("0", "1"):
            raise serializers.ValidationError("status 必须为 '0' 或 '1'。")
        return value

    def validate_run(self, value: str) -> list[str]:
        value = str(value).strip()
        if not value:
            return []
        runs = [v.strip() for v in value.split(",") if v.strip()]
        invalid = [v for v in runs if v not in self._VALID_RUN]
        if invalid:
            raise serializers.ValidationError(
                f"run 包含无效值: {', '.join(invalid)}，允许值为 0/1/2/3/-1。"
            )
        return runs


class DocChangeStatusSerializer(serializers.Serializer):
    """POST /document/change_status 入参验证。"""

    doc_id = serializers.CharField(max_length=64, help_text="文档 ID（必填）")
    status = serializers.CharField(max_length=2, help_text="状态值，必须为 '0' 或 '1'")

    def validate_status(self, value: str) -> str:
        if str(value) not in ("0", "1"):
            raise serializers.ValidationError("status 必须为 '0' 或 '1'。")
        return str(value)


class DocRunSerializer(serializers.Serializer):
    """POST /document/run 入参验证。"""

    doc_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        help_text="文档 ID 列表（必填，至少 1 个）",
    )
    run = serializers.CharField(max_length=2, help_text="运行状态: '0'=未运行, '1'=已完成, '2'=运行中, '3'=取消, '-1'=报错")
    delete = serializers.BooleanField(
        default=False,
        help_text="是否先删除已有 chunk 再重新解析，默认 false",
    )

    def validate_run(self, value: str) -> str:
        value = str(value)
        if value not in ("0", "1", "2", "3", "-1"):
            raise serializers.ValidationError("run 必须为 '0'、'1'、'2'、'3' 或 '-1'。")
        return value


class DocChangeParserSerializer(serializers.Serializer):
    """POST /document/change_parser 入参验证。"""

    doc_id = serializers.CharField(max_length=64, help_text="文档 ID（必填）")
    parser_id = serializers.CharField(max_length=32, help_text="解析器 ID（必填）")
    chunker_id = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        help_text="切分器 ID（可选，如 pdf_llm）",
    )
    chunker_config = serializers.JSONField(
        required=False, allow_null=True,
        help_text="切分器配置 JSON（可选）",
    )

    def validate_chunker_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("chunker_id 不能为空。")
        return value


class DocSetMetaSerializer(serializers.Serializer):
    """POST /document/set_meta 入参验证。"""

    doc_id = serializers.CharField(max_length=64, help_text="文档 ID（必填）")
    meta = serializers.JSONField(help_text="元数据，必须为 JSON 对象（dict）类型")

    def validate_meta(self, value: object) -> dict:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError) as exc:
                raise serializers.ValidationError(f"meta JSON 格式错误：{exc}") from exc
        if not isinstance(value, dict):
            raise serializers.ValidationError("meta 必须为 JSON 对象格式，如 {\"key\": \"value\"}。")
        return value  # type: ignore[return-value]


class DocRenameSerializer(serializers.Serializer):
    """POST /document/rename 入参验证。"""

    doc_id = serializers.CharField(max_length=64, help_text="文档 ID（必填）")
    name = serializers.CharField(max_length=255, help_text="新文件名（必填，扩展名不可修改）")

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("文件名不能为空。")
        return value


class DocRmSerializer(serializers.Serializer):
    """POST /document/rm 入参验证。

    doc_id 可以是单个文档 ID 字符串，也可以是 ID 列表。
    """

    doc_id = serializers.JSONField(help_text="文档 ID（字符串或字符串列表）")

    def validate_doc_id(self, value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            if not all(isinstance(v, str) for v in value):
                raise serializers.ValidationError("doc_id 列表中所有元素必须为字符串。")
            return value  # type: ignore[return-value]
        raise serializers.ValidationError("doc_id 必须为字符串或字符串列表。")


class DocBatchDownloadSerializer(serializers.Serializer):
    """POST /document/batch_download 入参验证。"""

    doc_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        help_text="文档 ID 列表（必填，至少 1 个）",
    )


class DocTaskListSerializer(serializers.Serializer):
    """GET /document/task/list 入参验证。"""

    kb_id = serializers.CharField(required=False, allow_blank=True, max_length=64, help_text="知识库 ID")
    doc_id = serializers.CharField(required=False, allow_blank=True, max_length=64, help_text="文档 ID")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
    page = serializers.IntegerField(default=1, min_value=1, help_text="页码")
    page_size = serializers.IntegerField(default=50, min_value=1, max_value=200, help_text="每页条数")


class DocVersionListSerializer(serializers.Serializer):
    """GET /document/version/list 入参验证。"""

    doc_id = serializers.CharField(max_length=64, help_text="文档 ID")
    tenant_id = serializers.CharField(required=False, default="", allow_blank=True, max_length=64, help_text="租户 ID")
