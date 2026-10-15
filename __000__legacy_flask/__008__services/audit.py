from __future__ import annotations

from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.ids import new_id
from __000__common.__003__orm.models import AuditLog


def write(user_id: str, action: str, target: str = "", detail: str = "") -> None:
    with session_scope() as session:
        session.add(
            AuditLog(id=new_id(), user_id=user_id or "", action=action, target=target, detail=detail[:2000])
        )


def list_recent(limit: int = 20) -> list[dict]:
    with session_scope() as session:
        rows = session.query(AuditLog).order_by(AuditLog.create_date.desc()).limit(limit).all()
        return [
            {
                "action": row.action,
                "target": row.target,
                "detail": row.detail or "",
                "user_id": row.user_id,
                "create_date": row.create_date.isoformat(sep=" ", timespec="seconds") if row.create_date else "",
            }
            for row in rows
        ]
