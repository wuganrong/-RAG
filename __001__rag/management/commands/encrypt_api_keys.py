from __future__ import annotations

from django.core.management.base import BaseCommand

from __001__rag.models import LLMFactories
from __001__rag.utils.secrets import protect_secret


class Command(BaseCommand):
    help = "将历史明文 LLM 厂商 API Key 转换为签名保护格式。"

    def handle(self, *args, **options):
        updated = 0
        for factory in LLMFactories.objects.exclude(api_key__isnull=True):
            raw = factory.api_key or ""
            protected = protect_secret(raw)
            if protected != raw:
                factory.api_key = protected
                factory.save(update_fields=["api_key", "update_date"])
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"API Key 加密处理完成，更新 {updated} 条。"))
