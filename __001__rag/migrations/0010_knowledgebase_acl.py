from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0009_tenant_quota"),
    ]

    operations = [
        migrations.CreateModel(
            name="KnowledgebaseAcl",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("kb_id", models.CharField(db_index=True, help_text="知识库ID", max_length=64, verbose_name="知识库ID")),
                ("subject_type", models.CharField(db_index=True, help_text="user / role", max_length=16, verbose_name="授权主体类型")),
                ("subject_id", models.CharField(db_index=True, help_text="用户ID或角色名", max_length=255, verbose_name="授权主体ID")),
                ("permission", models.CharField(db_index=True, default="read", help_text="read / write / admin", max_length=16, verbose_name="权限")),
                ("status", models.CharField(db_index=True, default="1", help_text="1 启用，0 禁用", max_length=1, verbose_name="状态")),
            ],
            options={
                "verbose_name": "知识库访问控制",
                "verbose_name_plural": "知识库访问控制",
                "db_table": "knowledgebase_acl",
                "unique_together": {("tenant_id", "kb_id", "subject_type", "subject_id")},
            },
        ),
    ]
