from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.ids import new_id
from __000__common.__003__orm.models import AssistantConfig, PromptTemplate, User

DEFAULT_PROMPT = (
    "你是企业知识库助手。只根据给定资料回答；找不到就明确说没有依据，不要编造。\n"
    "资料：\n{context}\n\n问题：{question}"
)


def seed_defaults() -> None:
    with session_scope() as session:
        if session.query(User).count() == 0:
            session.add(
                User(
                    id=new_id(),
                    username="admin",
                    password_hash=generate_password_hash("admin123"),
                    role="owner",
                )
            )
        if session.query(PromptTemplate).filter_by(prompt_key="default").first() is None:
            session.add(
                PromptTemplate(
                    id=new_id(),
                    prompt_key="default",
                    name="默认问答提示词",
                    system_prompt=DEFAULT_PROMPT,
                )
            )
        if session.query(AssistantConfig).filter_by(assistant_key="default").first() is None:
            session.add(
                AssistantConfig(
                    id=new_id(),
                    assistant_key="default",
                    assistant_name="默认助理",
                    prompt_key="default",
                    memory_rounds=5,
                )
            )


def authenticate(username: str, password: str) -> dict | None:
    with session_scope() as session:
        user = session.query(User).filter(User.username == username, User.status == "1").first()
        if user is None or not check_password_hash(user.password_hash, password):
            return None
        return {"id": user.id, "username": user.username, "role": user.role}


def get_user(user_id: str) -> dict | None:
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return None
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "daily_query_limit": user.daily_query_limit,
            "daily_upload_limit": user.daily_upload_limit,
        }


def require_role(role: str, needed: str) -> None:
    order = {"viewer": 0, "editor": 1, "owner": 2}
    if order.get(role, 0) < order.get(needed, 1):
        raise PermissionError("权限不足")
