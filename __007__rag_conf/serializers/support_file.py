"""rag_conf 应用的支持文件管理 Serializer。"""

from __future__ import annotations

from rest_framework import serializers


# ---------------------------------------------------------------------------
#  映射管理（FileTypeMapping）
# ---------------------------------------------------------------------------


class MappingListSerializer(serializers.Serializer):
    """映射列表 / 树形查询的入参验证。"""

    keywords = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="关键词，模糊匹配 file_type / parser_id / parser 的 display_name / method_class",
    )
    status = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=1,
        help_text="状态过滤，1 启用 / 0 禁用",
    )

    def validate_status(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value


class MappingSetSerializer(serializers.Serializer):
    """新增/更新文件类型映射的入参验证。"""

    id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=64,
        help_text="主键，更新时传入",
    )
    file_type = serializers.CharField(
        required=True,
        max_length=32,
        help_text="文件扩展名（如 pdf、docx）",
    )
    parser_id = serializers.CharField(
        required=True,
        max_length=32,
        help_text="解析方法标识",
    )
    status = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1,
        help_text="1 启用，0 禁用",
    )

    def validate_file_type(self, value: str) -> str:
        value = value.strip().lstrip(".").lower()
        if not value:
            raise serializers.ValidationError("文件类型不能为空。")
        return value

    def validate_parser_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("解析方法不能为空。")
        return value

    def validate_status(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value


class MappingChangeStatusSerializer(serializers.Serializer):
    """切换映射状态的入参验证。"""

    id = serializers.CharField(required=True, max_length=64, help_text="映射主键")
    status = serializers.CharField(required=True, max_length=1, help_text="1 启用，0 禁用")

    def validate_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("id 不能为空。")
        return value

    def validate_status(self, value: str) -> str:
        value = value.strip()
        if value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value


class MappingDeleteSerializer(serializers.Serializer):
    """删除单条映射的入参验证。"""

    id = serializers.CharField(required=True, max_length=64, help_text="映射主键")

    def validate_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("id 不能为空。")
        return value


class MappingRenameSerializer(serializers.Serializer):
    """重命名文件类型的入参验证。"""

    old_type = serializers.CharField(required=True, max_length=32, help_text="原文件类型")
    new_type = serializers.CharField(required=True, max_length=32, help_text="新文件类型")

    def validate_old_type(self, value: str) -> str:
        value = value.strip().lstrip(".").lower()
        if not value:
            raise serializers.ValidationError("原文件类型不能为空。")
        return value

    def validate_new_type(self, value: str) -> str:
        value = value.strip().lstrip(".").lower()
        if not value:
            raise serializers.ValidationError("新文件类型不能为空。")
        return value


class MappingBatchBindSerializer(serializers.Serializer):
    """批量绑定文件类型的入参验证。"""

    parser_id = serializers.CharField(required=True, max_length=32, help_text="解析方法标识")
    file_types = serializers.ListField(
        child=serializers.CharField(max_length=32),
        required=True,
        help_text="文件扩展名列表",
    )
    status = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1,
        help_text="1 启用，0 禁用，默认 1",
    )

    def validate_parser_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("解析方法不能为空。")
        return value

    def validate_file_types(self, value: list[str]) -> list[str]:
        cleaned = [v.strip().lstrip(".").lower() for v in value if isinstance(v, str)]
        cleaned = [v for v in cleaned if v]
        if not cleaned:
            raise serializers.ValidationError("请至少填写一个有效的文件类型。")
        return list(dict.fromkeys(cleaned))  # 去重且保持顺序

    def validate_status(self, value: str) -> str:
        value = value.strip()
        if value and value not in {"0", "1"}:
            raise serializers.ValidationError("status 只能为 0 或 1。")
        return value


class MappingRmByParserSerializer(serializers.Serializer):
    """按解析方法清空映射的入参验证。"""

    parser_id = serializers.CharField(required=True, max_length=32, help_text="解析方法标识")

    def validate_parser_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("解析方法不能为空。")
        return value


class MappingRmByTypeSerializer(serializers.Serializer):
    """按文件类型删除映射的入参验证。"""

    file_type = serializers.CharField(required=True, max_length=32, help_text="文件类型")

    def validate_file_type(self, value: str) -> str:
        value = value.strip().lstrip(".").lower()
        if not value:
            raise serializers.ValidationError("文件类型不能为空。")
        return value


# ---------------------------------------------------------------------------
#  方法管理（ChunkMethod）
# ---------------------------------------------------------------------------


class MethodListSerializer(serializers.Serializer):
    """方法库列表的入参验证。"""

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


class MethodSetSerializer(serializers.Serializer):
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


class MethodDeleteSerializer(serializers.Serializer):
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


class MethodChangeStatusSerializer(serializers.Serializer):
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


# ---------------------------------------------------------------------------
#  快捷查询
# ---------------------------------------------------------------------------


class MappingFileTypesSerializer(serializers.Serializer):
    """根据解析方法标识查询允许文件类型的入参验证。"""

    parser_id = serializers.CharField(
        required=True,
        max_length=32,
        help_text="解析方法标识（如 naive、mineru）",
    )

    def validate_parser_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("解析方法标识不能为空。")
        return value


class MappingParsersSerializer(serializers.Serializer):
    """根据文件类型查询可用解析方法的入参验证。"""

    file_type = serializers.CharField(
        required=True,
        max_length=32,
        help_text="文件类型（如 pdf、docx）",
    )

    def validate_file_type(self, value: str) -> str:
        value = value.strip().lstrip(".").lower()
        if not value:
            raise serializers.ValidationError("文件类型不能为空。")
        return value
