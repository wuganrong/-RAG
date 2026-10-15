from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0008_evaluation_result"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantQuota",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, unique=True, verbose_name="租户ID")),
                ("storage_quota_mb", models.IntegerField(default=10240, help_text="文档与页图存储配额", verbose_name="存储配额MB")),
                ("document_quota", models.IntegerField(default=1000, help_text="可上传文档数量", verbose_name="文档数量配额")),
                ("token_quota", models.IntegerField(default=1000000, help_text="模型调用总Token配额", verbose_name="Token配额")),
                ("vision_page_quota", models.IntegerField(default=5000, help_text="可索引页图数量", verbose_name="视觉页数配额")),
                ("model_call_quota", models.IntegerField(default=10000, help_text="模型调用次数配额", verbose_name="模型调用配额")),
                ("status", models.CharField(db_index=True, default="1", help_text="1 启用，0 禁用", max_length=1, verbose_name="状态")),
            ],
            options={"verbose_name": "租户配额", "verbose_name_plural": "租户配额", "db_table": "tenant_quota"},
        ),
    ]
