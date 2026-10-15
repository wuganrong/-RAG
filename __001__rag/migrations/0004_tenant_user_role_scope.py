from django.db import migrations, models

from __001__rag.models import TimestampField


def create_default_tenant(apps, schema_editor):
    Tenant = apps.get_model("rag", "Tenant")
    Tenant.objects.get_or_create(
        id="default",
        defaults={"name": "默认租户", "description": "兼容历史数据", "status": "1"},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0003_conversation_feedback"),
    ]

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("name", models.CharField(help_text="租户名称", max_length=128, unique=True, verbose_name="租户名称")),
                ("description", models.TextField(blank=True, help_text="租户描述", null=True, verbose_name="租户描述")),
                ("status", models.CharField(db_index=True, default="1", help_text="1 启用，0 禁用", max_length=1, verbose_name="状态")),
            ],
            options={"verbose_name": "租户", "verbose_name_plural": "租户", "db_table": "tenant"},
        ),
        migrations.CreateModel(
            name="UserRole",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("user_id", models.CharField(db_index=True, help_text="用户ID", max_length=255, verbose_name="用户ID")),
                ("user_name", models.CharField(blank=True, help_text="用户名称", max_length=128, null=True, verbose_name="用户名称")),
                ("role", models.CharField(db_index=True, default="viewer", help_text="admin / editor / viewer", max_length=32, verbose_name="角色")),
                ("status", models.CharField(db_index=True, default="1", help_text="1 启用，0 禁用", max_length=1, verbose_name="状态")),
            ],
            options={
                "verbose_name": "用户角色",
                "verbose_name_plural": "用户角色",
                "db_table": "user_role",
                "unique_together": {("tenant_id", "user_id")},
            },
        ),
        migrations.AddField(
            model_name="llm",
            name="tenant_id",
            field=models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID"),
        ),
        migrations.AddField(
            model_name="knowledgebase",
            name="tenant_id",
            field=models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID"),
        ),
        migrations.AddField(
            model_name="document",
            name="tenant_id",
            field=models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID"),
        ),
        migrations.AddField(
            model_name="conversation",
            name="tenant_id",
            field=models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID"),
        ),
        migrations.AddField(
            model_name="conversationfeedback",
            name="tenant_id",
            field=models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID"),
        ),
        migrations.AlterField(
            model_name="knowledgebase",
            name="name",
            field=models.CharField(help_text="知识库名称", max_length=128, verbose_name="知识库名称"),
        ),
        migrations.AlterUniqueTogether(
            name="llm",
            unique_together={("tenant_id", "fid", "llm_name")},
        ),
        migrations.AlterUniqueTogether(
            name="knowledgebase",
            unique_together={("tenant_id", "name")},
        ),
        migrations.AlterUniqueTogether(
            name="conversationfeedback",
            unique_together={("tenant_id", "conversation_id", "message_id", "user_id")},
        ),
        migrations.RunPython(create_default_tenant, migrations.RunPython.noop),
    ]

