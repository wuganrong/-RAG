from django.db import models
from django.utils import timezone


# =============================================================================
# 自定义字段
# =============================================================================


class TimestampField(models.DateTimeField):
    """MySQL TIMESTAMP 类型的 DateTimeField，使用 timezone.now() 自动填充时间。

    参数:
        auto_create: 仅在首次创建时自动填充（类似 auto_now_add）
        auto_update: 每次保存时自动填充（类似 auto_now）
    """

    def __init__(self, *args, auto_create: bool = False, auto_update: bool = False, **kwargs):
        self.auto_create = auto_create
        self.auto_update = auto_update
        super().__init__(*args, **kwargs)

    def db_type(self, connection):
        if connection.vendor == "mysql":
            return "TIMESTAMP"
        return super().db_type(connection)

    def pre_save(self, model_instance, add):
        if self.auto_create and add:
            value = timezone.now()
            setattr(model_instance, self.attname, value)
            return value
        if self.auto_update:
            value = timezone.now()
            setattr(model_instance, self.attname, value)
            return value
        return super().pre_save(model_instance, add)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.auto_create:
            kwargs["auto_create"] = True
        if self.auto_update:
            kwargs["auto_update"] = True
        return name, path, args, kwargs


# =============================================================================
# 基类
# =============================================================================


class BaseModel(models.Model):
    """所有业务模型的基类"""

    create_date = TimestampField(
        auto_create=True, null=True, db_index=True,
        verbose_name="创建时间", help_text="创建时间(日期格式)"
    )
    update_date = TimestampField(
        auto_update=True, null=True, db_index=True,
        verbose_name="更新时间", help_text="更新时间(日期格式)"
    )

    class Meta:
        abstract = True


# =============================================================================
# 租户与用户权限
# =============================================================================


class Tenant(BaseModel):
    """租户空间"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    name = models.CharField(max_length=128, unique=True, verbose_name="租户名称", help_text="租户名称")
    description = models.TextField(null=True, blank=True, verbose_name="租户描述", help_text="租户描述")
    status = models.CharField(max_length=1, default="1", db_index=True, verbose_name="状态", help_text="1 启用，0 禁用")

    class Meta:
        db_table = "tenant"
        verbose_name = "租户"
        verbose_name_plural = "租户"


class UserRole(BaseModel):
    """用户角色绑定"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    user_id = models.CharField(max_length=255, db_index=True, verbose_name="用户ID", help_text="用户ID")
    user_name = models.CharField(max_length=128, null=True, blank=True, verbose_name="用户名称", help_text="用户名称")
    role = models.CharField(max_length=32, default="viewer", db_index=True, verbose_name="角色", help_text="admin / editor / viewer")
    status = models.CharField(max_length=1, default="1", db_index=True, verbose_name="状态", help_text="1 启用，0 禁用")

    class Meta:
        db_table = "user_role"
        verbose_name = "用户角色"
        verbose_name_plural = "用户角色"
        unique_together = [("tenant_id", "user_id")]


class TenantQuota(BaseModel):
    """租户资源配额"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, unique=True, db_index=True, default="default", verbose_name="租户ID", help_text="租户ID")
    storage_quota_mb = models.IntegerField(default=10240, verbose_name="存储配额MB", help_text="文档与页图存储配额")
    document_quota = models.IntegerField(default=1000, verbose_name="文档数量配额", help_text="可上传文档数量")
    token_quota = models.IntegerField(default=1000000, verbose_name="Token配额", help_text="模型调用总Token配额")
    vision_page_quota = models.IntegerField(default=5000, verbose_name="视觉页数配额", help_text="可索引页图数量")
    model_call_quota = models.IntegerField(default=10000, verbose_name="模型调用配额", help_text="模型调用次数配额")
    status = models.CharField(max_length=1, default="1", db_index=True, verbose_name="状态", help_text="1 启用，0 禁用")

    class Meta:
        db_table = "tenant_quota"
        verbose_name = "租户配额"
        verbose_name_plural = "租户配额"


# =============================================================================
# 词表（系统字典 / 替换同义词 / NER）
# =============================================================================


class SysDict(BaseModel):
    """字典"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    parent_id = models.CharField(
        max_length=128, null=False, db_index=True,
        verbose_name="父级ID", help_text="父级ID"
    )
    key = models.CharField(
        max_length=255, null=True, db_index=True,
        verbose_name="键", help_text="键"
    )
    value = models.CharField(
        max_length=255, null=True,
        verbose_name="值", help_text="值"
    )
    remark = models.CharField(
        max_length=1, null=True,
        verbose_name="备注", help_text="备注"
    )
    status = models.CharField(
        max_length=1, null=True, default="1",
        verbose_name="状态", help_text="状态(1:正常, 0:禁用)"
    )

    class Meta:
        db_table = "sys_dict"
        verbose_name = "字典"
        verbose_name_plural = "字典"


class ReplaceSynonym(BaseModel):
    """替换同义词表"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    dict = models.CharField(
        max_length=100, null=True, db_index=True,
        verbose_name="核心词", help_text="核心词"
    )
    synonym = models.CharField(
        max_length=100, null=True,
        verbose_name="同义词", help_text="同义词"
    )
    status = models.CharField(
        max_length=1, null=True, default="0",
        verbose_name="状态", help_text="状态(0:有效，1:无效)"
    )

    class Meta:
        db_table = "replace_synonym"
        verbose_name = "替换同义词"
        verbose_name_plural = "替换同义词"


class NerDict(BaseModel):
    """词典表"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    tag = models.CharField(
        max_length=20, null=True,
        verbose_name="标签类型", help_text="标签类型(ner, dict, synonym)"
    )
    type = models.CharField(
        max_length=100, null=True,
        verbose_name="业务类型", help_text="业务类型(如:toxic, stock, firstnm)"
    )
    dict = models.CharField(
        max_length=100, null=True, db_index=True,
        verbose_name="词典词", help_text="词典词"
    )
    synonym = models.CharField(
        max_length=1000, null=True,
        verbose_name="同义词列表", help_text="同义词列表"
    )
    f = models.BigIntegerField(
        null=True,
        verbose_name="词频", help_text="词频"
    )
    n = models.CharField(
        max_length=32, null=True,
        verbose_name="词性", help_text="词性"
    )
    status = models.CharField(
        max_length=1, null=False, default="0",
        verbose_name="状态", help_text="状态(0:有效，1:无效)"
    )
    remark = models.CharField(
        max_length=255, null=True,
        verbose_name="备注", help_text="备注"
    )
    create_by = models.CharField(
        max_length=64, null=True,
        verbose_name="创建人", help_text="创建人"
    )
    update_by = models.CharField(
        max_length=64, null=True,
        verbose_name="更新人", help_text="更新人"
    )

    class Meta:
        db_table = "ner_dict"
        verbose_name = "NER词典"
        verbose_name_plural = "NER词典"


# =============================================================================
# LLM（厂商 / 模型）
# =============================================================================


class LLMFactories(BaseModel):
    """大模型厂商"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    name = models.CharField(
        max_length=128, unique=True, null=False,
        verbose_name="厂商名称", help_text="厂商名称(唯一标识)"
    )
    api_key = models.CharField(
        max_length=2048, null=True,
        verbose_name="API密钥", help_text="API密钥"
    )
    api_base = models.CharField(
        max_length=255, null=True,
        verbose_name="API基础URL", help_text="API基础URL"
    )
    status = models.CharField(
        max_length=1, null=True, default="1",
        verbose_name="状态", help_text="状态(1:正常, 0:禁用)"
    )

    class Meta:
        db_table = "llm_factories"
        verbose_name = "大模型厂商"
        verbose_name_plural = "大模型厂商"


class APIKeyRotationLog(BaseModel):
    """API Key 轮换记录"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    factory_name = models.CharField(max_length=128, db_index=True, verbose_name="厂商名称", help_text="厂商名称")
    operator = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="操作人", help_text="操作人")
    action = models.CharField(max_length=32, default="rotate", db_index=True, verbose_name="动作", help_text="rotate / encrypt")
    old_key_masked = models.CharField(max_length=64, null=True, blank=True, verbose_name="旧Key脱敏", help_text="旧Key脱敏")
    new_key_masked = models.CharField(max_length=64, null=True, blank=True, verbose_name="新Key脱敏", help_text="新Key脱敏")

    class Meta:
        db_table = "api_key_rotation_log"
        verbose_name = "API Key轮换记录"
        verbose_name_plural = "API Key轮换记录"


class AlertRecord(BaseModel):
    """系统告警记录"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    alert_type = models.CharField(max_length=64, db_index=True, verbose_name="告警类型", help_text="告警类型")
    level = models.CharField(max_length=16, default="warning", db_index=True, verbose_name="级别", help_text="info / warning / critical")
    title = models.CharField(max_length=255, verbose_name="标题", help_text="标题")
    message = models.TextField(null=True, blank=True, verbose_name="消息", help_text="消息")
    status = models.CharField(max_length=16, default="open", db_index=True, verbose_name="状态", help_text="open / resolved")
    detail = models.JSONField(default=dict, verbose_name="详情", help_text="详情")

    class Meta:
        db_table = "alert_record"
        verbose_name = "系统告警记录"
        verbose_name_plural = "系统告警记录"


class LLM(BaseModel):
    """大模型基础信息"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    llm_name = models.CharField(
        max_length=128, null=False, db_index=True,
        verbose_name="模型名称", help_text="模型名称"
    )
    model_type = models.CharField(
        max_length=128, null=False, db_index=True,
        verbose_name="模型类型", help_text="模型类型"
    )
    fid = models.CharField(
        max_length=128, null=False, db_index=True,
        verbose_name="关联厂商名称", help_text="关联厂商名称(唯一标识)"
    )
    tenant_id = models.CharField(
        max_length=64, null=False, default="default", db_index=True,
        verbose_name="租户ID", help_text="租户ID"
    )
    max_tokens = models.IntegerField(
        null=False, default=0,
        verbose_name="最大Token数", help_text="模型支持的最大Token数"
    )
    status = models.CharField(
        max_length=1, null=True, default="1",
        verbose_name="状态", help_text="状态(1:正常, 0:下架)"
    )

    class Meta:
        db_table = "llm"
        verbose_name = "大模型基础信息"
        verbose_name_plural = "大模型基础信息"
        unique_together = [("tenant_id", "fid", "llm_name")]


# =============================================================================
# 知识库（库 / 文档 / 解析任务 / 文件关联）
# =============================================================================


class Knowledgebase(BaseModel):
    """知识库"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    name = models.CharField(
        max_length=128, null=False,
        verbose_name="知识库名称", help_text="知识库名称"
    )
    tenant_id = models.CharField(
        max_length=64, null=False, default="default", db_index=True,
        verbose_name="租户ID", help_text="租户ID"
    )
    avatar = models.TextField(
        null=True,
        verbose_name="知识库头像URL", help_text="知识库头像URL"
    )
    description = models.TextField(
        null=True,
        verbose_name="知识库描述", help_text="知识库描述"
    )
    embd_id = models.CharField(
        max_length=128, null=False,
        verbose_name="向量模型ID", help_text="使用的向量模型ID"
    )
    permission = models.CharField(
        max_length=16, null=False,
        verbose_name="权限", help_text="权限"
    )
    created_by = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="创建人ID", help_text="创建人ID"
    )
    doc_num = models.IntegerField(
        null=False, default=0,
        verbose_name="文档数量", help_text="文档数量"
    )
    chunk_num = models.IntegerField(
        null=False, default=0,
        verbose_name="分块数量", help_text="分块数量"
    )
    parser_id = models.CharField(
        max_length=32, null=False,
        verbose_name="解析器ID", help_text="解析器ID"
    )
    chunker_id = models.CharField(
        max_length=32, null=False,
        verbose_name="文本切分器ID", help_text="文本切分器ID"
    )
    chunker_config = models.JSONField(
        null=False, default=dict,
        verbose_name="文本切分器配置", help_text="文本切分器配置"
    )
    status = models.CharField(
        max_length=1, null=True, default="1",
        verbose_name="状态", help_text="状态(1:正常, 0:禁用)"
    )
    rag_mode = models.CharField(
        max_length=16, null=False, default="vision",
        verbose_name="检索模式", help_text="text / vision / hybrid"
    )
    vlm_id = models.CharField(
        max_length=128, null=False, default="qwen-vl-plus",
        verbose_name="视觉模型ID", help_text="页图问答使用的 VLM"
    )
    page_top_n = models.IntegerField(
        null=False, default=3,
        verbose_name="页图召回数量", help_text="ColPali 返回的页数"
    )
    page_num = models.IntegerField(
        null=False, default=0,
        verbose_name="页图数量", help_text="视觉索引中的页数"
    )

    class Meta:
        db_table = "knowledgebase"
        verbose_name = "知识库"
        verbose_name_plural = "知识库"
        unique_together = [("tenant_id", "name")]


class KnowledgebaseAcl(BaseModel):
    """知识库访问控制"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    kb_id = models.CharField(max_length=64, db_index=True, verbose_name="知识库ID", help_text="知识库ID")
    subject_type = models.CharField(max_length=16, db_index=True, verbose_name="授权主体类型", help_text="user / role")
    subject_id = models.CharField(max_length=255, db_index=True, verbose_name="授权主体ID", help_text="用户ID或角色名")
    permission = models.CharField(max_length=16, default="read", db_index=True, verbose_name="权限", help_text="read / write / admin")
    status = models.CharField(max_length=1, default="1", db_index=True, verbose_name="状态", help_text="1 启用，0 禁用")

    class Meta:
        db_table = "knowledgebase_acl"
        verbose_name = "知识库访问控制"
        verbose_name_plural = "知识库访问控制"
        unique_together = [("tenant_id", "kb_id", "subject_type", "subject_id")]


class Document(BaseModel):
    """文档"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    thumbnail = models.TextField(
        null=True,
        verbose_name="文档缩略图URL", help_text="文档缩略图URL"
    )
    kb_id = models.CharField(
        max_length=256, null=False, db_index=True,
        verbose_name="所属知识库ID", help_text="所属知识库ID"
    )
    tenant_id = models.CharField(
        max_length=64, null=False, default="default", db_index=True,
        verbose_name="租户ID", help_text="租户ID"
    )
    embd_id = models.CharField(
        max_length=128, null=True,
        verbose_name="向量模型ID", help_text="使用的向量模型ID"
    )
    parser_id = models.CharField(
        max_length=32, null=False,
        verbose_name="解析器ID", help_text="解析器ID"
    )
    chunker_id = models.CharField(
        max_length=32, null=False,
        verbose_name="文本切分器ID", help_text="文本切分器ID"
    )
    chunker_config = models.JSONField(
        null=False, default=dict,
        verbose_name="文本切分器配置", help_text="文本切分器配置"
    )
    source_type = models.CharField(
        max_length=128, null=False, default="local", db_index=True,
        verbose_name="来源类型", help_text="来源类型(如:local, s3)"
    )
    type = models.CharField(
        max_length=32, null=False,
        verbose_name="文件类型", help_text="文件类型(如:pdf, docx, md)"
    )
    created_by = models.CharField(
        max_length=32, null=False,
        verbose_name="上传人ID", help_text="上传人ID"
    )
    name = models.CharField(
        max_length=255, null=True, db_index=True,
        verbose_name="文件名称", help_text="文件名称"
    )
    location = models.CharField(
        max_length=255, null=True,
        verbose_name="文件存储路径", help_text="文件存储路径"
    )
    size = models.IntegerField(
        null=False, default=0,
        verbose_name="文件大小", help_text="文件大小"
    )
    token_num = models.IntegerField(
        null=False, default=0,
        verbose_name="解析消耗Token数", help_text="解析消耗的Token数"
    )
    chunk_num = models.IntegerField(
        null=False, default=0,
        verbose_name="Chunk数量", help_text="切分出的Chunk数量"
    )
    progress = models.FloatField(
        null=False, default=0.0, db_index=True,
        verbose_name="解析进度", help_text="解析进度(0~1)"
    )
    progress_msg = models.TextField(
        null=True,
        verbose_name="进度提示信息", help_text="进度提示信息"
    )
    process_begin_at = models.DateTimeField(
        null=True, db_index=True,
        verbose_name="开始处理时间", help_text="开始处理时间"
    )
    process_duration = models.FloatField(
        null=False, default=0.0,
        verbose_name="处理耗时", help_text="处理耗时(秒)"
    )
    meta_fields = models.JSONField(
        null=True, default=dict,
        verbose_name="文档元数据", help_text="文档元数据"
    )
    run = models.CharField(
        max_length=2, null=True, default="0",
        verbose_name="运行状态", help_text="运行状态(0:未运行, 1:已完成, 2:运行中, 3:取消, -1:报错)"
    )
    status = models.CharField(
        max_length=2, null=True, default="0",
        verbose_name="启用状态", help_text="启用状态(0:未启用, 1:启用)"
    )
    label = models.CharField(
        max_length=1024, null=True,
        verbose_name="文档标签", help_text="文档标签"
    )
    remote_id = models.CharField(
        max_length=32, null=True,
        verbose_name="远端文件ID", help_text="远端文件ID"
    )
    index_modes = models.CharField(
        max_length=32, null=False, default="",
        verbose_name="已建索引模式", help_text="逗号分隔，如 text,vision"
    )
    page_num = models.IntegerField(
        null=False, default=0,
        verbose_name="页图数量", help_text="该文档写入视觉索引的页数"
    )

    class Meta:
        db_table = "document"
        verbose_name = "文档"
        verbose_name_plural = "文档"


# Document.run 常量
RUN_IDLE = "0"      # 未运行
RUN_DONE = "1"      # 已完成
RUN_RUNNING = "2"   # 运行中
RUN_CANCEL = "3"    # 取消
RUN_ERROR = "-1"    # 报错

# Document.status 常量
STATUS_DISABLED = "0"  # 未启用
STATUS_ENABLED = "1"   # 启用


class File(BaseModel):
    """文件信息"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    name = models.CharField(
        max_length=255, null=False, db_index=True,
        verbose_name="文件名称", help_text="文件名称"
    )
    parent_id = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="父文件夹ID", help_text="父文件夹ID"
    )
    created_by = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="上传人ID", help_text="上传人ID"
    )
    location = models.CharField(
        max_length=255, null=True,
        verbose_name="文件存储路径", help_text="文件存储路径"
    )
    size = models.IntegerField(
        null=False, default=0,
        verbose_name="文件大小", help_text="文件大小"
    )
    type = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="文件类型", help_text="文件类型(文件夹:folder, 文件:doc等)"
    )
    source_type = models.CharField(
        max_length=128, null=False, default="",
        verbose_name="来源类型", help_text="来源类型"
    )

    class Meta:
        db_table = "file"
        verbose_name = "文件信息"
        verbose_name_plural = "文件信息"


class File2Document(BaseModel):
    """文档与文件关联"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    file_id = models.CharField(
        max_length=32, null=True, db_index=True,
        verbose_name="文件ID", help_text="文件ID"
    )
    document_id = models.CharField(
        max_length=32, null=True, db_index=True,
        verbose_name="文档ID", help_text="文档ID"
    )

    class Meta:
        db_table = "file2document"
        verbose_name = "文档与文件关联"
        verbose_name_plural = "文档与文件关联"


class Task(BaseModel):
    """文档解析任务"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    doc_id = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="关联文档ID", help_text="关联文档ID"
    )
    from_page = models.IntegerField(
        null=False, default=0,
        verbose_name="起始页码", help_text="起始页码"
    )
    to_page = models.IntegerField(
        null=False, default=100000000,
        verbose_name="结束页码", help_text="结束页码"
    )
    task_type = models.CharField(
        max_length=32, null=False, default="",
        verbose_name="任务类型", help_text="任务类型"
    )
    begin_at = models.DateTimeField(
        null=True, db_index=True,
        verbose_name="任务开始时间", help_text="任务开始时间"
    )
    process_duration = models.FloatField(
        null=False, default=0.0,
        verbose_name="处理耗时", help_text="处理耗时(秒)"
    )
    progress = models.FloatField(
        null=False, default=0.0, db_index=True,
        verbose_name="任务进度", help_text="任务进度(0~1)"
    )
    progress_msg = models.TextField(
        null=True,
        verbose_name="进度提示信息", help_text="进度提示信息"
    )
    retry_count = models.IntegerField(
        null=False, default=0,
        verbose_name="重试次数", help_text="重试次数"
    )
    digest = models.TextField(
        null=True,
        verbose_name="任务摘要信息", help_text="任务摘要信息"
    )
    chunk_ids = models.TextField(
        null=True,
        verbose_name="Chunk ID列表", help_text="生成的Chunk ID列表(JSON数组)"
    )
    priority = models.IntegerField(
        null=False, default=0,
        verbose_name="任务优先级", help_text="任务优先级"
    )

    class Meta:
        db_table = "task"
        verbose_name = "文档解析任务"
        verbose_name_plural = "文档解析任务"


# =============================================================================
# 缓存（解析与 LLM 中间结果缓存）
# =============================================================================


class PdfLlmSectionRawCache(BaseModel):
    """LLM章节提取原始缓存"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    section_id = models.CharField(
        max_length=128, null=True, db_index=True,
        verbose_name="章节ID", help_text="章节ID"
    )
    title = models.CharField(
        max_length=512, null=True,
        verbose_name="章节标题", help_text="章节标题"
    )
    parent_title = models.CharField(
        max_length=512, null=True,
        verbose_name="父章节标题", help_text="父章节标题"
    )
    parse_method = models.CharField(
        max_length=255, null=True,
        verbose_name="解析方法", help_text="解析方法"
    )
    doc_id = models.CharField(
        max_length=64, null=True,
        verbose_name="文档ID", help_text="文档ID"
    )
    kb_id = models.CharField(
        max_length=64, null=True,
        verbose_name="知识库ID", help_text="知识库ID"
    )
    input_sha256 = models.CharField(
        max_length=64, null=False, db_index=True,
        verbose_name="输入内容哈希", help_text="输入内容哈希"
    )
    raw_response = models.TextField(
        null=False,
        verbose_name="LLM原始返回", help_text="LLM原始返回结果"
    )
    file_name = models.CharField(
        max_length=255, null=True,
        verbose_name="文件名称", help_text="文件名称"
    )
    section_content = models.TextField(
        null=True,
        verbose_name="提取的章节内容", help_text="提取的章节内容"
    )
    status = models.CharField(
        max_length=1, null=False, default="1",
        verbose_name="状态", help_text="状态(0:无效，1:有效)"
    )

    class Meta:
        db_table = "pdf_llm_section_raw_cache"
        verbose_name = "LLM章节提取原始缓存"
        verbose_name_plural = "LLM章节提取原始缓存"


class DocToMarkdownCache(BaseModel):
    """文档解析Markdown缓存"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    pdf_sha256 = models.CharField(
        max_length=64, unique=True,
        verbose_name="PDF文件SHA256", help_text="PDF文件SHA256哈希值"
    )
    doc_id = models.CharField(
        max_length=64, null=True, db_index=True,
        verbose_name="文档ID", help_text="文档ID"
    )
    file_name = models.CharField(
        max_length=255, null=True, db_index=True,
        verbose_name="文件名称", help_text="文件名称"
    )
    size_bytes = models.BigIntegerField(
        null=False, default=0,
        verbose_name="文件大小", help_text="文件大小"
    )
    markdown_content = models.TextField(
        null=False,
        verbose_name="Markdown内容", help_text="解析出的Markdown内容"
    )
    status = models.CharField(
        max_length=1, null=False, default="1",
        verbose_name="状态", help_text="状态(0:无效，1:有效)"
    )
    parse_method = models.CharField(
        max_length=32, null=False,
        verbose_name="解析方法", help_text="解析方法/模型"
    )

    class Meta:
        db_table = "doc_to_markdown_cache"
        verbose_name = "文档解析Markdown缓存"
        verbose_name_plural = "文档解析Markdown缓存"


class DocImagesCache(BaseModel):
    """识别文档图片缓存"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    cache_id = models.BigIntegerField(
        null=False, db_index=True,
        verbose_name="文档识别缓存表ID", help_text="文档识别缓存表ID"
    )
    image_key = models.CharField(
        max_length=255, null=False, db_index=True,
        verbose_name="图片标识", help_text="图片标识"
    )
    image_data = models.TextField(
        null=False,
        verbose_name="base64图片数据", help_text="base64 image data"
    )
    bucket = models.CharField(
        max_length=128, null=True,
        verbose_name="存储桶标识", help_text="存储桶标识"
    )
    remote_url = models.CharField(
        max_length=1024, null=True,
        verbose_name="远程存储地址", help_text="远程存储地址"
    )
    status = models.IntegerField(
        null=True,
        verbose_name="状态", help_text="状态：0无效，1有效"
    )

    class Meta:
        db_table = "doc_images_cache"
        verbose_name = "识别文档图片缓存"
        verbose_name_plural = "识别文档图片缓存"


# =============================================================================
# 方法配置（文档提取与切分 / 检索 等方法注册）
# =============================================================================


class ChunkMethod(BaseModel):
    """文档提取和切分方法配置

    config_schema 字段为 JSON 数组（默认 []），每个元素描述一个表单控件。

    Field 对象（数组中的每个元素）
    --------------------------------------------
    字段          类型                必填   说明
    -----------   ----------------   ----   -----------------------------------------------
    key           string             必填   对应 chunker_config JSON 中的键名，表单数据按此键读写
    label         string             必填   表单 label 显示文本
    type          WidgetType         必填   控件类型，可选值：
                                             "input"    — 单行文本输入框
                                             "textarea" — 多行文本输入框
                                             "number"   — 数字输入框
                                             "select"   — 下拉选择框（需配合 props.options）
                                             "switch"   — 开关（boolean）
                                             "slider"   — 滑块
                                             "radio"    — 单选按钮组
                                             "checkbox" — 多选框组
    default       any                必填   默认值。切换 chunker 时用此值初始化表单
    required      boolean            可选   是否必填，默认 false
    placeholder   string             可选   输入框占位提示文字
    tooltip       string             可选   label 旁 ? 图标的悬浮提示，给用户解释该参数的作用
    props         Record<str, any>   可选   透传给 Element Plus 组件的属性。
                                             示例（number）：{"min": 128, "max": 2048, "step": 64}
                                             示例（select）：{"options": [{"label": "精确", "value": "exact"}]}
    rules         FormRule[]         可选   Element Plus el-form 校验规则列表，格式：
                                             [{"required": true, "message": "不能为空", "trigger": "blur"},
                                              {"min": 1, "max": 100, "message": "范围 1~100"}]
    col_span      number             可选   栅格占位（24 列体系）。默认 24（独占一行），12 表示半行并列

    完整示例：
    [
      {
        "key": "chunk_token_num",
        "label": "Chunk Token 数量",
        "type": "number",
        "default": 512,
        "required": true,
        "tooltip": "每个切片包含的最大 token 数",
        "props": {"min": 128, "max": 2048, "step": 64},
        "rules": [{"required": true, "message": "不能为空", "trigger": "blur"}],
        "col_span": 12
      },
      {
        "key": "delimiter",
        "label": "分隔符",
        "type": "input",
        "default": "\\n\\n",
        "placeholder": "段落分隔符",
        "col_span": 12
      },
      {
        "key": "auto_keywords",
        "label": "自动关键词提取",
        "type": "slider",
        "default": 0,
        "tooltip": "自动为切片生成关键词的最大数量，0 表示不提取",
        "props": {"min": 0, "max": 30, "show_input": true},
        "col_span": 12
      }
    ]
    """

    method = models.CharField(
        max_length=32, db_index=True,
        verbose_name="方法标识", help_text="方法标识(如: naive, qa, mineru)"
    )
    method_type = models.CharField(
        max_length=16, null=False, db_index=True, default='chunker',
        verbose_name="方法类型", help_text="方法类型(chunker: 切分方法, parser: 文档提取方法)"
    )
    display_name = models.CharField(
        max_length=128, null=False, default="",
        verbose_name="前端显示名称", help_text="前端展示的切分方法名称"
    )
    method_class = models.CharField(
        max_length=255, null=False,
        verbose_name="方法类路径", help_text="方法类完整导入路径"
    )
    status = models.CharField(
        max_length=1, null=False, default="1",
        verbose_name="状态", help_text="状态(1:启用, 0:禁用)"
    )
    config_schema = models.JSONField(
        default=list,
        verbose_name="动态表单 Schema",
        help_text=(
            "JSON 数组，每个元素描述一个表单控件。"
            "必填字段：key（chunker_config 键名）、label（显示文本）、"
            "type（控件类型，可选 input/textarea/number/select/switch/slider/radio/checkbox）、"
            "default（默认值，切换 chunker 时初始化表单）。"
            "可选字段：required / placeholder / tooltip / "
            "props（透传给 Element Plus，如 {min,max,step,options}）/ "
            "rules（el-form 校验规则列表）/ "
            "col_span（栅格列数，24 列体系，默认 24 独占一行）。"
        )
    )

    class Meta:
        db_table = "document_method_config"
        verbose_name = "文档提取和切分方法配置"
        verbose_name_plural = "文档提取和切分方法配置"


class RetrievalMethod(BaseModel):
    """检索方法配置"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    method = models.CharField(
        max_length=32, unique=True, db_index=True,
        verbose_name="方法标识", help_text="方法标识(如: vector, keyword, hybrid)"
    )
    display_name = models.CharField(
        max_length=128, null=False, default="",
        verbose_name="显示名称", help_text="前端展示的检索方法名称"
    )
    method_class = models.CharField(
        max_length=255, null=False,
        verbose_name="方法类路径", help_text="方法类完整导入路径"
    )
    status = models.CharField(
        max_length=1, null=False, default="1",
        verbose_name="状态", help_text="状态(1:启用, 0:禁用)"
    )

    class Meta:
        db_table = "retrieval_method_config"
        verbose_name = "检索方法配置"
        verbose_name_plural = "检索方法配置"


# =============================================================================
# 提示词（可复用的提示模板）
# =============================================================================


class PromptConfig(BaseModel):
    """提示词管理表"""

    id = models.AutoField(
        primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    config_key = models.CharField(
        max_length=64, unique=True,
        verbose_name="模板唯一键", help_text="模板唯一键(如: chat)"
    )
    section_name = models.CharField(
        max_length=255, null=True, blank=True,
        verbose_name="提示词名称", help_text="提示词名称"
    )
    system_prompt = models.TextField(
        null=True, blank=True,
        verbose_name="系统提示词(System Prompt)", help_text="系统提示词"
    )
    user_prompt_template = models.TextField(
        null=True, blank=True,
        verbose_name="用户提示词模板", help_text="用户提示词模板，支持变量如 {query}、{context}"
    )
    status = models.CharField(
        max_length=1, default="1",
        verbose_name="是否启用", help_text="是否启用(1:启用, 0:禁用)"
    )

    class Meta:
        db_table = "prompt_config"
        verbose_name = "提示词管理表"
        verbose_name_plural = "提示词管理表"


# =============================================================================
# 助理（场景编排 / 会话 / 意图）
# =============================================================================


class AssistantType(models.TextChoices):
    """助理交互类型：对话或任务。"""

    CONVERSATION = "conversation", "对话"
    TASK = "task", "任务"


class AssistantConfig(BaseModel):
    """助理配置表"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    assistant_key = models.CharField(
        max_length=64, unique=True,
        verbose_name="助理唯一键", help_text="业务唯一标识(如: chat、customer_service)"
    )
    assistant_type = models.CharField(
        max_length=16,
        choices=AssistantType.choices,
        default=AssistantType.CONVERSATION,
        verbose_name="助理类型", help_text="对话型或任务型"
    )
    assistant_name = models.CharField(
        max_length=128, null=True, blank=True,
        verbose_name="助理名称", help_text="助理名称"
    )
    # 逻辑关联提示词模板
    prompt_config_key = models.CharField(
        max_length=64,
        verbose_name="关联提示词模板Key", help_text="关联提示词模板的唯一键"
    )
    # 模型参数
    model_name = models.CharField(
        max_length=128, null=True, blank=True,
        verbose_name="模型名称", help_text="模型名称"
    )
    llm_setting = models.JSONField(
        default=dict,
        verbose_name="JSON格式参数", help_text="JSON格式参数(如: {\"temperature\": 0.1})"
    )
    max_tokens = models.IntegerField(
        null=True, blank=True,
        verbose_name="最大token数", help_text="最大 token 数"
    )
    extra_params = models.JSONField(
        default=dict,
        verbose_name="其他create参数", help_text="其他 create 参数 JSON"
    )
    # 检索增强参数
    retrieval_method = models.CharField(
        max_length=32, null=True, blank=True,
        verbose_name="检索方法标识", help_text="关联检索方法配置的 method 字段值"
    )
    similarity_threshold = models.FloatField(
        default=0.2,
        verbose_name="相似度阈值", help_text="相似度阈值"
    )
    vector_similarity_weight = models.FloatField(
        default=0.3,
        verbose_name="向量相似度权重", help_text="向量相似度权重"
    )
    top_n = models.IntegerField(
        default=6,
        verbose_name="召回向量数量", help_text="召回向量数量"
    )
    rerank_id = models.CharField(
        max_length=128, null=True, blank=True,
        verbose_name="重排模型ID", help_text="重排模型ID"
    )
    # 知识库关联
    kb_ids = models.JSONField(
        default=list,
        verbose_name="关联知识库ID列表", help_text="关联知识库ID列表"
    )
    # 对话控制
    memory_rounds = models.IntegerField(
        default=5,
        verbose_name="记忆轮数", help_text="多轮对话记忆轮数"
    )
    top_k = models.IntegerField(
        default=1024,
        verbose_name="生成Top_K参数", help_text="生成Top_K参数"
    )
    # 用户交互
    prologue = models.TextField(
        null=True, blank=True,
        verbose_name="开场白", help_text="对话开场白"
    )
    # 状态
    status = models.CharField(
        max_length=1, default="1",
        verbose_name="是否启用", help_text="是否启用(1:启用, 0:禁用)"
    )

    class Meta:
        db_table = "assistant_config"
        verbose_name = "助理配置"
        verbose_name_plural = verbose_name


class Conversation(BaseModel):
    """会话记录"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    model = models.CharField(
        max_length=255, null=False, default="",
        verbose_name="会话使用的模型", help_text="会话使用的模型"
    )
    name = models.CharField(
        max_length=255, null=True,
        verbose_name="会话标题", help_text="会话标题/名称"
    )
    message = models.TextField(
        null=True,
        verbose_name="完整消息记录", help_text="完整消息记录(JSON)"
    )
    reference = models.TextField(
        null=True,
        verbose_name="引用的chunks信息", help_text="引用的 chunks 信息(JSON)"
    )
    user_id = models.CharField(
        max_length=255, null=True, db_index=True,
        verbose_name="发起会话的用户ID", help_text="发起会话的用户ID"
    )
    tenant_id = models.CharField(
        max_length=64, null=False, default="default", db_index=True,
        verbose_name="租户ID", help_text="租户ID"
    )

    class Meta:
        db_table = "conversation"
        verbose_name = "会话记录"
        verbose_name_plural = "会话记录"


class ConversationFeedback(BaseModel):
    """会话回答反馈"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    conversation_id = models.CharField(
        max_length=64, db_index=True,
        verbose_name="会话ID", help_text="会话ID"
    )
    message_id = models.CharField(
        max_length=64, db_index=True,
        verbose_name="消息ID", help_text="被评价的 assistant 消息 ID"
    )
    user_id = models.CharField(
        max_length=255, null=True, blank=True, db_index=True,
        verbose_name="用户ID", help_text="反馈用户ID"
    )
    tenant_id = models.CharField(
        max_length=64, null=False, default="default", db_index=True,
        verbose_name="租户ID", help_text="租户ID"
    )
    rating = models.CharField(
        max_length=16, db_index=True,
        verbose_name="反馈结果", help_text="useful / useless"
    )
    reason = models.CharField(
        max_length=64, null=True, blank=True,
        verbose_name="反馈原因", help_text="无用或低质量原因"
    )
    comment = models.TextField(
        null=True, blank=True,
        verbose_name="反馈备注", help_text="用户补充说明"
    )

    class Meta:
        db_table = "conversation_feedback"
        verbose_name = "会话回答反馈"
        verbose_name_plural = "会话回答反馈"
        unique_together = [("tenant_id", "conversation_id", "message_id", "user_id")]


class AuditLog(BaseModel):
    """操作审计日志"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    user_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="用户ID", help_text="用户ID")
    action = models.CharField(max_length=64, db_index=True, verbose_name="操作", help_text="操作类型")
    resource_type = models.CharField(max_length=64, db_index=True, verbose_name="资源类型", help_text="资源类型")
    resource_id = models.CharField(max_length=128, null=True, blank=True, db_index=True, verbose_name="资源ID", help_text="资源ID")
    detail = models.JSONField(null=False, default=dict, verbose_name="详情", help_text="操作详情")
    status = models.CharField(max_length=16, default="success", db_index=True, verbose_name="结果", help_text="success / failed")

    class Meta:
        db_table = "audit_log"
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"


class UsageLog(BaseModel):
    """模型与问答用量日志"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    user_id = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="用户ID", help_text="用户ID")
    conversation_id = models.CharField(max_length=64, null=True, blank=True, db_index=True, verbose_name="会话ID", help_text="会话ID")
    kb_ids = models.JSONField(null=False, default=list, verbose_name="知识库ID列表", help_text="知识库ID列表")
    model = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="模型", help_text="模型")
    call_type = models.CharField(max_length=32, default="chat", db_index=True, verbose_name="调用类型", help_text="chat / embedding / vlm / rerank")
    prompt_tokens = models.IntegerField(default=0, verbose_name="输入Token", help_text="输入Token")
    completion_tokens = models.IntegerField(default=0, verbose_name="输出Token", help_text="输出Token")
    total_tokens = models.IntegerField(default=0, verbose_name="总Token", help_text="总Token")
    duration_ms = models.IntegerField(default=0, verbose_name="耗时毫秒", help_text="耗时毫秒")
    status = models.CharField(max_length=16, default="success", db_index=True, verbose_name="结果", help_text="success / failed")
    error = models.TextField(null=True, blank=True, verbose_name="错误信息", help_text="错误信息")

    class Meta:
        db_table = "usage_log"
        verbose_name = "用量日志"
        verbose_name_plural = "用量日志"


class DocumentVersion(BaseModel):
    """文档版本记录"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    kb_id = models.CharField(max_length=64, db_index=True, verbose_name="知识库ID", help_text="知识库ID")
    document_id = models.CharField(max_length=64, db_index=True, verbose_name="文档ID", help_text="文档ID")
    version = models.IntegerField(default=1, verbose_name="版本号", help_text="版本号")
    file_name = models.CharField(max_length=255, verbose_name="文件名", help_text="文件名")
    file_size = models.BigIntegerField(default=0, verbose_name="文件大小", help_text="文件大小")
    location = models.CharField(max_length=255, null=True, blank=True, verbose_name="存储位置", help_text="存储位置")
    is_current = models.CharField(max_length=1, default="1", db_index=True, verbose_name="当前版本", help_text="1 当前，0 历史")
    created_by = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="创建人", help_text="创建人")

    class Meta:
        db_table = "document_version"
        verbose_name = "文档版本"
        verbose_name_plural = "文档版本"
        unique_together = [("document_id", "version")]


class EvaluationQuestion(BaseModel):
    """评测问题集"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    kb_id = models.CharField(max_length=64, db_index=True, verbose_name="知识库ID", help_text="知识库ID")
    question = models.TextField(verbose_name="问题", help_text="问题")
    expected_answer = models.TextField(null=True, blank=True, verbose_name="期望答案", help_text="期望答案")
    tags = models.JSONField(default=list, verbose_name="标签", help_text="标签")
    status = models.CharField(max_length=1, default="1", db_index=True, verbose_name="状态", help_text="1 启用，0 禁用")

    class Meta:
        db_table = "evaluation_question"
        verbose_name = "评测问题"
        verbose_name_plural = "评测问题"


class EvaluationResult(BaseModel):
    """评测执行结果"""

    id = models.CharField(max_length=64, primary_key=True, verbose_name="主键", help_text="主键")
    tenant_id = models.CharField(max_length=64, default="default", db_index=True, verbose_name="租户ID", help_text="租户ID")
    kb_id = models.CharField(max_length=64, db_index=True, verbose_name="知识库ID", help_text="知识库ID")
    question_id = models.CharField(max_length=64, db_index=True, verbose_name="问题ID", help_text="问题ID")
    question = models.TextField(verbose_name="问题", help_text="问题")
    expected_answer = models.TextField(null=True, blank=True, verbose_name="期望答案", help_text="期望答案")
    text_hit_count = models.IntegerField(default=0, verbose_name="文本召回数", help_text="文本召回数")
    vision_hit_count = models.IntegerField(default=0, verbose_name="视觉召回数", help_text="视觉召回数")
    has_reference = models.CharField(max_length=1, default="0", db_index=True, verbose_name="是否有引用", help_text="1 是，0 否")
    expected_hit = models.CharField(max_length=1, default="0", db_index=True, verbose_name="期望命中", help_text="1 是，0 否")
    score = models.FloatField(default=0.0, verbose_name="得分", help_text="0-1")
    detail = models.JSONField(default=dict, verbose_name="详情", help_text="评测详情")
    status = models.CharField(max_length=16, default="success", db_index=True, verbose_name="状态", help_text="success / failed")
    error = models.TextField(null=True, blank=True, verbose_name="错误", help_text="错误信息")

    class Meta:
        db_table = "evaluation_result"
        verbose_name = "评测结果"
        verbose_name_plural = "评测结果"


class IntentionType(BaseModel):
    """意图识别配置"""

    id = models.AutoField(
        primary_key=True,
        verbose_name="主键", help_text="主键"
    )

    # 树形结构核心字段
    parent_id = models.IntegerField(
        null=True, blank=True, db_index=True,
        verbose_name="父意图ID", help_text="父意图的ID，根节点留空"
    )
    path = models.CharField(
        max_length=500, null=True, blank=True,
        verbose_name="路径", help_text="从根到当前节点的路径，如 /服务咨询/售后/退换货"
    )
    depth = models.IntegerField(
        default=0, verbose_name="层级深度", help_text="根节点为0"
    )
    intent_type = models.CharField(
        max_length=1, choices=[('C', '分类节点'), ('T', '任务节点')], default='T',
        verbose_name="意图类型", help_text="分类节点仅路由，任务节点触发实际执行"
    )

    # 原有字段
    intention = models.CharField(
        max_length=30, null=True,
        verbose_name="意图名称", help_text="意图名称"
    )
    status = models.CharField(
        max_length=1, null=True, default="1",
        verbose_name="状态", help_text="状态(1:有效，0:无效)"
    )
    is_default = models.CharField(
        max_length=1, null=True, default="0",
        verbose_name="是否默认意图", help_text="是否默认意图(1:是, 0:否)"
    )
    kb_ids = models.JSONField(
        null=False, default=list,
        verbose_name="关联知识库ID列表", help_text="关联知识库ID列表"
    )
    sys_prompt = models.TextField(
        null=True,
        verbose_name="系统提示词", help_text="系统提示词"
    )
    intention_description = models.TextField(
        null=True,
        verbose_name="意图描述说明", help_text="意图描述说明"
    )

    # 新增策略字段
    inherit_slots = models.BooleanField(
        default=False, verbose_name="继承父槽位",
        help_text="是否自动继承所有父级意图已定义的槽位"
    )
    child_match_policy = models.CharField(
        max_length=1,
        choices=[('F', '全执行'), ('C', '条件分支'), ('L', 'LLM判别')],
        default='L',
        verbose_name="子意图匹配策略",
        help_text="匹配到该节点后，如何处理多个子意图"
    )
    is_fallback = models.BooleanField(
        default=False, verbose_name="是否为兜底意图",
        help_text="在同层级中作为兜底选项，仅一个为True"
    )

    class Meta:
        db_table = "intention_type"
        verbose_name = "意图识别配置"
        verbose_name_plural = "意图识别配置"


# =============================================================================
# 最近操作 / 文件类型映射
# =============================================================================


class RecentActivity(BaseModel):
    """最近操作记录"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    activity_type = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="资源类型", help_text="资源类型(knowledgebase, document, task)"
    )
    message = models.CharField(
        max_length=512, null=False,
        verbose_name="操作描述", help_text="操作描述"
    )

    class Meta:
        db_table = "recent_activity"
        verbose_name = "最近操作记录"
        verbose_name_plural = "最近操作记录"


class FileTypeMapping(BaseModel):
    """支持解析的文件类型及对应解析方法、切分方法"""

    id = models.CharField(
        max_length=64, primary_key=True,
        verbose_name="主键", help_text="主键"
    )
    file_type = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="文件类型", help_text="文件扩展名(pdf, docx, md, txt, xlsx 等)"
    )
    parser_id = models.CharField(
        max_length=32, null=False, db_index=True,
        verbose_name="解析方法", help_text="解析方法标识，对应 document_method_config.method(method_type=parser)"
    )
    status = models.CharField(
        max_length=1, null=False, default="1",
        verbose_name="状态", help_text="状态(1:启用, 0:禁用)"
    )

    class Meta:
        db_table = "file_type_mapping"
        verbose_name = "支持解析文件类型及对应方法"
        verbose_name_plural = "支持解析文件类型及对应方法"
        unique_together = [("file_type", "parser_id")]
