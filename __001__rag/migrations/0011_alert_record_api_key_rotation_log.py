from django.db import migrations, models

from __001__rag.models import TimestampField


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0010_knowledgebase_acl"),
    ]

    operations = [
        migrations.CreateModel(
            name="APIKeyRotationLog",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("factory_name", models.CharField(db_index=True, help_text="厂商名称", max_length=128, verbose_name="厂商名称")),
                ("operator", models.CharField(blank=True, db_index=True, help_text="操作人", max_length=255, null=True, verbose_name="操作人")),
                ("action", models.CharField(db_index=True, default="rotate", help_text="rotate / encrypt", max_length=32, verbose_name="动作")),
                ("old_key_masked", models.CharField(blank=True, help_text="旧Key脱敏", max_length=64, null=True, verbose_name="旧Key脱敏")),
                ("new_key_masked", models.CharField(blank=True, help_text="新Key脱敏", max_length=64, null=True, verbose_name="新Key脱敏")),
            ],
            options={"verbose_name": "API Key轮换记录", "verbose_name_plural": "API Key轮换记录", "db_table": "api_key_rotation_log"},
        ),
        migrations.CreateModel(
            name="AlertRecord",
            fields=[
                ("create_date", TimestampField(auto_create=True, db_index=True, help_text="创建时间(日期格式)", null=True, verbose_name="创建时间")),
                ("update_date", TimestampField(auto_update=True, db_index=True, help_text="更新时间(日期格式)", null=True, verbose_name="更新时间")),
                ("id", models.CharField(help_text="主键", max_length=64, primary_key=True, serialize=False, verbose_name="主键")),
                ("tenant_id", models.CharField(db_index=True, default="default", help_text="租户ID", max_length=64, verbose_name="租户ID")),
                ("alert_type", models.CharField(db_index=True, help_text="告警类型", max_length=64, verbose_name="告警类型")),
                ("level", models.CharField(db_index=True, default="warning", help_text="info / warning / critical", max_length=16, verbose_name="级别")),
                ("title", models.CharField(help_text="标题", max_length=255, verbose_name="标题")),
                ("message", models.TextField(blank=True, help_text="消息", null=True, verbose_name="消息")),
                ("status", models.CharField(db_index=True, default="open", help_text="open / resolved", max_length=16, verbose_name="状态")),
                ("detail", models.JSONField(default=dict, help_text="详情", verbose_name="详情")),
            ],
            options={"verbose_name": "系统告警记录", "verbose_name_plural": "系统告警记录", "db_table": "alert_record"},
        ),
    ]
