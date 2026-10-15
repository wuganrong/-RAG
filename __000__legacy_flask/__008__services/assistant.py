from __future__ import annotations

from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.models import AssistantConfig, PromptTemplate
from __008__services.auth import DEFAULT_PROMPT


def resolve_assistant(kb_id: str | None = None) -> dict:
    with session_scope() as session:
        row = None
        if kb_id:
            row = session.query(AssistantConfig).filter_by(kb_id=kb_id, status="1").first()
        if row is None:
            row = session.query(AssistantConfig).filter_by(assistant_key="default", status="1").first()
        prompt = None
        if row is not None:
            prompt = session.query(PromptTemplate).filter_by(prompt_key=row.prompt_key, status="1").first()
        return {
            "assistant_key": row.assistant_key if row else "default",
            "chat_id": row.chat_id if row else "qwen-plus",
            "memory_rounds": row.memory_rounds if row else 5,
            "prompt": (prompt.system_prompt if prompt else DEFAULT_PROMPT),
        }


def render_prompt(template: str, question: str, context: str, history: str = "") -> str:
    text = template or DEFAULT_PROMPT
    return (
        text.replace("{question}", question)
        .replace("{context}", context or "（无）")
        .replace("{history}", history or "（无）")
    )
