from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0007_evaluation_question"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvaluationResult",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("kb_id", models.CharField(db_index=True, help_text="知识库ID", max_length=64, verbose_name="知识库ID")),
                ("question_id", models.CharField(db_index=True, help_text="问题ID", max_length=64, verbose_name="问题ID")),
                ("question", models.TextField(help_text="问题", verbose_name="问题")),
                ("expected_answer", models.TextField(blank=True, help_text="期望答案", null=True, verbose_name="期望答案")),
                ("text_hit_count", models.IntegerField(default=0, help_text="文本召回数", verbose_name="文本召回数")),
                ("vision_hit_count", models.IntegerField(default=0, help_text="视觉召回数", verbose_name="视觉召回数")),
                ("has_reference", models.CharField(db_index=True, default="0", help_text="1 是，0 否", max_length=1, verbose_name="是否有引用")),
                ("expected_hit", models.CharField(db_index=True, default="0", help_text="1 是，0 否", max_length=1, verbose_name="期望命中")),
                ("score", models.FloatField(default=0.0, help_text="0-1", verbose_name="得分")),
                ("detail", models.JSONField(default=dict, help_text="评测详情", verbose_name="详情")),
                ("status", models.CharField(db_index=True, default="success", help_text="success / failed", max_length=16, verbose_name="状态")),
                ("error", models.TextField(blank=True, help_text="错误信息", null=True, verbose_name="错误")),
            ],
            options={"verbose_name": "评测结果", "verbose_name_plural": "评测结果", "db_table": "evaluation_result"},
        ),
    ]

