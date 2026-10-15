from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0006_document_version"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvaluationQuestion",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("kb_id", models.CharField(db_index=True, help_text="知识库ID", max_length=64, verbose_name="知识库ID")),
                ("question", models.TextField(help_text="问题", verbose_name="问题")),
                ("expected_answer", models.TextField(blank=True, help_text="期望答案", null=True, verbose_name="期望答案")),
                ("tags", models.JSONField(default=list, help_text="标签", verbose_name="标签")),
                ("status", models.CharField(db_index=True, default="1", help_text="1 启用，0 禁用", max_length=1, verbose_name="状态")),
            ],
            options={"verbose_name": "评测问题", "verbose_name_plural": "评测问题", "db_table": "evaluation_question"},
        ),
    ]

