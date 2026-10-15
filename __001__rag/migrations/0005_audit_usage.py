from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0004_tenant_user_role_scope"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("user_id", models.CharField(blank=True, db_index=True, help_text="用户ID", max_length=255, null=True, verbose_name="用户ID")),
                ("action", models.CharField(db_index=True, help_text="操作类型", max_length=64, verbose_name="操作")),
                ("resource_type", models.CharField(db_index=True, help_text="资源类型", max_length=64, verbose_name="资源类型")),
                ("resource_id", models.CharField(blank=True, db_index=True, help_text="资源ID", max_length=128, null=True, verbose_name="资源ID")),
                ("detail", models.JSONField(default=dict, help_text="操作详情", verbose_name="详情")),
                ("status", models.CharField(db_index=True, default="success", help_text="success / failed", max_length=16, verbose_name="结果")),
            ],
            options={"verbose_name": "审计日志", "verbose_name_plural": "审计日志", "db_table": "audit_log"},
        ),
        migrations.CreateModel(
            name="UsageLog",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("user_id", models.CharField(blank=True, db_index=True, help_text="用户ID", max_length=255, null=True, verbose_name="用户ID")),
                ("conversation_id", models.CharField(blank=True, db_index=True, help_text="会话ID", max_length=64, null=True, verbose_name="会话ID")),
                ("kb_ids", models.JSONField(default=list, help_text="知识库ID列表", verbose_name="知识库ID列表")),
                ("model", models.CharField(blank=True, db_index=True, help_text="模型", max_length=255, null=True, verbose_name="模型")),
                ("call_type", models.CharField(db_index=True, default="chat", help_text="chat / embedding / vlm / rerank", max_length=32, verbose_name="调用类型")),
                ("prompt_tokens", models.IntegerField(default=0, help_text="输入Token", verbose_name="输入Token")),
                ("completion_tokens", models.IntegerField(default=0, help_text="输出Token", verbose_name="输出Token")),
                ("total_tokens", models.IntegerField(default=0, help_text="总Token", verbose_name="总Token")),
                ("duration_ms", models.IntegerField(default=0, help_text="耗时毫秒", verbose_name="耗时毫秒")),
                ("status", models.CharField(db_index=True, default="success", help_text="success / failed", max_length=16, verbose_name="结果")),
                ("error", models.TextField(blank=True, help_text="错误信息", null=True, verbose_name="错误信息")),
            ],
            options={"verbose_name": "用量日志", "verbose_name_plural": "用量日志", "db_table": "usage_log"},
        ),
    ]

