from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0002_rag_mode"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationFeedback",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("conversation_id", models.CharField(db_index=True, help_text="会话ID", max_length=64, verbose_name="会话ID")),
                ("message_id", models.CharField(db_index=True, help_text="被评价的 assistant 消息 ID", max_length=64, verbose_name="消息ID")),
                ("user_id", models.CharField(blank=True, db_index=True, help_text="反馈用户ID", max_length=255, null=True, verbose_name="用户ID")),
                ("rating", models.CharField(db_index=True, help_text="useful / useless", max_length=16, verbose_name="反馈结果")),
                ("reason", models.CharField(blank=True, help_text="无用或低质量原因", max_length=64, null=True, verbose_name="反馈原因")),
                ("comment", models.TextField(blank=True, help_text="用户补充说明", null=True, verbose_name="反馈备注")),
            ],
            options={
                "verbose_name": "会话回答反馈",
                "verbose_name_plural": "会话回答反馈",
                "db_table": "conversation_feedback",
                "unique_together": {("conversation_id", "message_id", "user_id")},
            },
        ),
    ]

