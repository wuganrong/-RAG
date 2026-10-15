"""chunker 应用的文档切块请求参数验证 Serializer。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from rest_framework import serializers


class _StringListField(serializers.ListField):
    """兼容前端传入列表或逗号分隔字符串。"""

    child = serializers.CharField()

    def to_internal_value(self, data: Any) -> list[str]:
        if isinstance(data, str):
            data = [item.strip() for item in data.split(",") if item.strip()]
        return super().to_internal_value(data)


class ChunkListSerializer(serializers.Serializer):
    """切片列表查询入参。"""

    doc_id = serializers.CharField(required=True, help_text="文档 ID")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="页码，从 1 开始")
    size = serializers.IntegerField(required=False, default=30, min_value=1, help_text="每页条数")
    keywords = serializers.CharField(required=False, allow_blank=True, default="", help_text="内容关键词")
    available_int = serializers.IntegerField(required=False, help_text="可用状态过滤，1=启用，0=停用")


class ChunkSwitchSerializer(serializers.Serializer):
    """切片启停入参。"""

    doc_id = serializers.CharField(required=True, help_text="文档 ID")
    chunk_ids = _StringListField(required=True, allow_empty=False, help_text="切片 ID 列表")
    available_int = serializers.IntegerField(required=True, help_text="可用状态，1=启用，0=停用")


class ChunkRmSerializer(serializers.Serializer):
    """切片删除入参。"""

    doc_id = serializers.CharField(required=True, help_text="文档 ID")
    chunk_ids = _StringListField(required=True, allow_empty=False, help_text="切片 ID 列表")


class ChunkCreateSerializer(serializers.Serializer):
    """创建切片入参。"""

    doc_id = serializers.CharField(required=True, help_text="文档 ID")
    content_with_weight = serializers.CharField(required=True, allow_blank=False, help_text="切片内容")
    important_kwd = _StringListField(required=False, default=list, help_text="关键词列表")
    question_kwd = _StringListField(required=False, default=list, help_text="关联问题列表")
    tag_kwd = _StringListField(required=False, default=list, help_text="标签列表")
    available_int = serializers.IntegerField(required=False, default=1, help_text="可用状态")


class ChunkGetSerializer(serializers.Serializer):
    """获取切片详情入参。"""

    chunk_id = serializers.CharField(required=True, help_text="切片 ID")
    doc_id = serializers.CharField(required=False, allow_blank=True, help_text="文档 ID")
    kb_id = serializers.CharField(required=False, allow_blank=True, help_text="知识库 ID")


class ChunkSetSerializer(serializers.Serializer):
    """更新切片入参。"""

    doc_id = serializers.CharField(required=True, help_text="文档 ID")
    chunk_id = serializers.CharField(required=True, help_text="切片 ID")
    content_with_weight = serializers.CharField(required=True, allow_blank=False, help_text="切片内容")
    important_kwd = _StringListField(required=False, help_text="关键词列表")
    question_kwd = _StringListField(required=False, help_text="关联问题列表")
    tag_kwd = _StringListField(required=False, help_text="标签列表")
    available_int = serializers.IntegerField(required=False, help_text="可用状态")


class ChunkRetrievalSerializer(serializers.Serializer):
    """检索测试与知识库检索入参。"""

    kb_id = _StringListField(required=False, allow_empty=True, default=list, help_text="知识库 ID 或 ID 列表")
    question = serializers.CharField(required=True, allow_blank=False, help_text="检索问题")
    doc_ids = _StringListField(required=False, allow_empty=True, default=list, help_text="限定文档 ID 列表")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="页码，从 1 开始")
    size = serializers.IntegerField(required=False, default=30, min_value=1, help_text="每页条数")
    top_k = serializers.IntegerField(required=False, default=1024, min_value=1, help_text="候选召回数量")
    similarity_threshold = serializers.FloatField(required=False, default=0.0, help_text="相似度阈值")
    vector_similarity_weight = serializers.FloatField(required=False, default=0.3, help_text="向量相似度权重")
    rerank_id = serializers.CharField(required=False, allow_blank=True, default="", help_text="重排模型 ID")
    use_kg = serializers.BooleanField(required=False, default=False, help_text="是否使用知识图谱")
    decomposition = serializers.IntegerField(required=False, default=0, help_text="是否问题分解")
    need_rerank = serializers.IntegerField(required=False, default=0, help_text="是否重排")
    highlight = serializers.BooleanField(required=False, default=False, help_text="是否高亮")


class ChunkItemResponseSerializer(serializers.Serializer):
    """切片接口返回的单条 chunk 字段。"""

    chunk_id = serializers.CharField(help_text="切片 ID")
    content_with_weight = serializers.CharField(help_text="带权重的切片正文")
    doc_id = serializers.CharField(help_text="文档 ID")
    docnm_kwd = serializers.CharField(help_text="文档名称")
    chunk_title_kwd = serializers.CharField(required=False, allow_blank=True, help_text="切片标题")
    important_kwd = _StringListField(required=False, help_text="关键词列表")
    question_kwd = _StringListField(required=False, help_text="关联问题列表")
    image_id = serializers.CharField(required=False, allow_blank=True, help_text="图片 ID")
    available_int = serializers.IntegerField(required=False, help_text="可用状态，1=启用，0=停用")
    positions = serializers.ListField(required=False, help_text="原文位置")
    parent_group_id = serializers.CharField(required=False, allow_blank=True, help_text="父子分块父组 ID")
    chunk_order = serializers.CharField(required=False, allow_blank=True, help_text="切片顺序")
    chunk_labels = serializers.ListField(required=False, help_text="MinerU/PDF LLM 标签字段")
    similarity = serializers.FloatField(required=False, default=0.0, help_text="混合相似度")
    vector_similarity = serializers.FloatField(required=False, default=0.0, help_text="向量相似度")
    term_similarity = serializers.FloatField(required=False, default=0.0, help_text="关键词相似度")


class ChunkListDataSerializer(serializers.Serializer):
    """切片列表响应 data 字段。"""

    total = serializers.IntegerField(help_text="总数")
    chunks = ChunkItemResponseSerializer(many=True, help_text="切片列表")
    doc = serializers.DictField(help_text="文档信息")


class ChunkRetrievalDataSerializer(serializers.Serializer):
    """检索响应 data 字段。"""

    chunks = ChunkItemResponseSerializer(many=True, help_text="召回切片")
    labels = serializers.ListField(required=False, allow_null=True, help_text="兼容旧版标签字段")
    total = serializers.IntegerField(help_text="总数")
    doc_aggs = serializers.ListField(help_text="文档聚合")
    questions = _StringListField(required=False, help_text="问题列表")


class ChunkListResponseSerializer(serializers.Serializer):
    """统一切片列表响应。"""

    code = serializers.IntegerField(help_text="业务状态码，0 表示成功")
    message = serializers.CharField(help_text="响应消息")
    data = ChunkListDataSerializer(help_text="响应数据")


class ChunkRetrievalResponseSerializer(serializers.Serializer):
    """统一切片检索响应。"""

    code = serializers.IntegerField(help_text="业务状态码，0 表示成功")
    message = serializers.CharField(help_text="响应消息")
    data = ChunkRetrievalDataSerializer(help_text="响应数据")


class GenericChunkResponseSerializer(serializers.Serializer):
    """通用 chunk 接口响应。"""

    code = serializers.IntegerField(help_text="业务状态码，0 表示成功")
    message = serializers.CharField(help_text="响应消息")
    data = serializers.JSONField(help_text="响应数据")


class ChunkMethodResponseSerializer(serializers.Serializer):
    """切片方法列表响应（旧格式，逗号分隔字符串）。"""

    code = serializers.IntegerField(help_text="业务状态码，0 表示成功")
    message = serializers.CharField(help_text="响应消息")
    data = serializers.CharField(help_text="切片方法字符串，如 naive:General,qa:Q&A")


class ChunkMethodItemSerializer(serializers.Serializer):
    """单个切片方法的结构化描述（detail=1 时使用）。"""

    method = serializers.CharField(help_text="方法标识，如 naive、qa、mineru")
    display_name = serializers.CharField(help_text="前端显示名称")
    method_type = serializers.CharField(help_text="方法类型：chunker / parser")
    config_schema = serializers.JSONField(
        help_text=(
            "JSON 数组，每个元素描述一个表单控件。"
            "必填字段：key（chunker_config 键名）/ label / type / default。"
            "可选字段：required / placeholder / tooltip / props / rules / col_span。"
            "空数组 [] 表示该 chunker 暂无自定义参数。"
        )
    )


class ChunkMethodDetailedResponseSerializer(serializers.Serializer):
    """切片方法列表响应（详细格式，含 config_schema）。"""

    code = serializers.IntegerField(help_text="业务状态码，0 表示成功")
    message = serializers.CharField(help_text="响应消息")
    data = ChunkMethodItemSerializer(many=True, help_text="切片方法列表")

