"""租户隔离自检命令。"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from __001__rag.models import (
    Conversation,
    ConversationFeedback,
    Document,
    EvaluationQuestion,
    EvaluationResult,
    Knowledgebase,
    LLM,
    Tenant,
)


class Command(BaseCommand):
    help = "检查核心业务表 tenant_id 是否完整，以及文档和知识库租户是否一致。"

    def handle(self, *args, **options):
        issues: list[str] = []

        if not Tenant.objects.filter(id="default").exists():
            issues.append("缺少 default 租户。")

        checks = [
            ("knowledgebase", Knowledgebase),
            ("document", Document),
            ("conversation", Conversation),
            ("conversation_feedback", ConversationFeedback),
            ("llm", LLM),
            ("evaluation_question", EvaluationQuestion),
            ("evaluation_result", EvaluationResult),
        ]
        for name, model in checks:
            missing = model.objects.filter(tenant_id__isnull=True).count()
            blank = model.objects.filter(tenant_id="").count()
            if missing or blank:
                issues.append(f"{name} 存在空 tenant_id：null={missing} blank={blank}")

        kb_tenants = dict(Knowledgebase.objects.values_list("id", "tenant_id"))
        for doc_id, kb_id, tenant_id in Document.objects.values_list("id", "kb_id", "tenant_id"):
            kb_tenant = kb_tenants.get(kb_id)
            if kb_tenant and kb_tenant != tenant_id:
                issues.append(f"document({doc_id}) tenant_id={tenant_id} 与 kb({kb_id}) tenant_id={kb_tenant} 不一致。")

        for qid, kb_id, tenant_id in EvaluationQuestion.objects.values_list("id", "kb_id", "tenant_id"):
            kb_tenant = kb_tenants.get(kb_id)
            if kb_tenant and kb_tenant != tenant_id:
                issues.append(f"evaluation_question({qid}) tenant_id={tenant_id} 与 kb({kb_id}) tenant_id={kb_tenant} 不一致。")

        if issues:
            self.stdout.write(self.style.ERROR(f"租户隔离检查发现 {len(issues)} 个问题："))
            for item in issues:
                self.stdout.write(f"- {item}")
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("租户隔离检查通过。"))
