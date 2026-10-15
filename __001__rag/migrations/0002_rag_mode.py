from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgebase",
            name="rag_mode",
            field=models.CharField(default="vision", help_text="text / vision / hybrid", max_length=16, verbose_name="检索模式"),
        ),
        migrations.AddField(
            model_name="knowledgebase",
            name="vlm_id",
            field=models.CharField(default="qwen-vl-plus", help_text="页图问答使用的 VLM", max_length=128, verbose_name="视觉模型ID"),
        ),
        migrations.AddField(
            model_name="knowledgebase",
            name="page_top_n",
            field=models.IntegerField(default=3, help_text="ColPali 返回的页数", verbose_name="页图召回数量"),
        ),
        migrations.AddField(
            model_name="knowledgebase",
            name="page_num",
            field=models.IntegerField(default=0, help_text="视觉索引中的页数", verbose_name="页图数量"),
        ),
        migrations.AddField(
            model_name="document",
            name="index_modes",
            field=models.CharField(default="", help_text="逗号分隔，如 text,vision", max_length=32, verbose_name="已建索引模式"),
        ),
        migrations.AddField(
            model_name="document",
            name="page_num",
            field=models.IntegerField(default=0, help_text="该文档写入视觉索引的页数", verbose_name="页图数量"),
        ),
    ]
