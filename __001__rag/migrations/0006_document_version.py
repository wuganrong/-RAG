from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0005_audit_usage"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentVersion",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("kb_id", models.CharField(db_index=True, help_text="知识库ID", max_length=64, verbose_name="知识库ID")),
                ("document_id", models.CharField(db_index=True, help_text="文档ID", max_length=64, verbose_name="文档ID")),
                ("version", models.IntegerField(default=1, help_text="版本号", verbose_name="版本号")),
                ("file_name", models.CharField(help_text="文件名", max_length=255, verbose_name="文件名")),
                ("file_size", models.BigIntegerField(default=0, help_text="文件大小", verbose_name="文件大小")),
                ("location", models.CharField(blank=True, help_text="存储位置", max_length=255, null=True, verbose_name="存储位置")),
                ("is_current", models.CharField(db_index=True, default="1", help_text="1 当前，0 历史", max_length=1, verbose_name="当前版本")),
                ("created_by", models.CharField(blank=True, db_index=True, help_text="创建人", max_length=255, null=True, verbose_name="创建人")),
            ],
            options={
                "verbose_name": "文档版本",
                "verbose_name_plural": "文档版本",
                "db_table": "document_version",
                "unique_together": {("document_id", "version")},
            },
        ),
    ]

