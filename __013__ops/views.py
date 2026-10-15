"""用量统计与审计日志接口。"""

from __future__ import annotations

from typing import Any
import logging
import socket
from urllib.parse import urlparse
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Sum
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from __001__rag.models import AlertRecord, AuditLog, ConversationFeedback, EvaluationResult, UsageLog
from __001__rag.ops import request_tenant_id, request_user_id, write_audit
from __001__rag.utils.ids import get_uuid
from __001__rag.utils import error_response, format_datetime, success_response

from .serializers import AuditQuerySerializer, UsageQuerySerializer

logger = logging.getLogger(__name__)


MODEL_PRICE = {
    "chat": {"input_per_1k": 0.002, "output_per_1k": 0.006},
    "embedding": {"input_per_1k": 0.0007, "output_per_1k": 0},
    "rerank": {"input_per_1k": 0.001, "output_per_1k": 0},
    "vlm": {"input_per_1k": 0.003, "output_per_1k": 0.009},
}


def _usage_to_dict(row: UsageLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id or "",
        "conversation_id": row.conversation_id or "",
        "kb_ids": row.kb_ids or [],
        "model": row.model or "",
        "call_type": row.call_type,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "total_tokens": row.total_tokens,
        "duration_ms": row.duration_ms,
        "status": row.status,
        "error": row.error or "",
        "create_date": format_datetime(row.create_date),
    }


def _audit_to_dict(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id or "",
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id or "",
        "detail": row.detail or {},
        "status": row.status,
        "create_date": format_datetime(row.create_date),
    }


@extend_schema(tags=["ops"], summary="用量概览", responses={200: None})
@api_view(["GET"])
def usage_summary(request: Request) -> Response:
    ser = UsageQuerySerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    qs = UsageLog.objects.filter(tenant_id=vd.get("tenant_id") or "default")
    if vd.get("user_id"):
        qs = qs.filter(user_id=vd["user_id"])
    if vd.get("model"):
        qs = qs.filter(model=vd["model"])
    agg = qs.aggregate(
        calls=Count("id"),
        total_tokens=Sum("total_tokens"),
        avg_duration_ms=Avg("duration_ms"),
    )
    failed = qs.filter(status="failed").count()
    by_model = list(qs.values("model").annotate(calls=Count("id"), total_tokens=Sum("total_tokens")).order_by("-calls")[:20])
    return success_response({
        "calls": agg["calls"] or 0,
        "failed": failed,
        "total_tokens": agg["total_tokens"] or 0,
        "avg_duration_ms": round(float(agg["avg_duration_ms"] or 0), 1),
        "by_model": by_model,
    })


@extend_schema(tags=["ops"], summary="成本估算概览", responses={200: None})
@api_view(["GET"])
def cost_summary(request: Request) -> Response:
    ser = UsageQuerySerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    qs = UsageLog.objects.filter(tenant_id=vd.get("tenant_id") or "default")
    if vd.get("user_id"):
        qs = qs.filter(user_id=vd["user_id"])
    if vd.get("model"):
        qs = qs.filter(model=vd["model"])

    rows: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    for item in qs.values("model", "call_type").annotate(
        calls=Count("id"),
        prompt_tokens=Sum("prompt_tokens"),
        completion_tokens=Sum("completion_tokens"),
        total_tokens=Sum("total_tokens"),
    ):
        call_type = item["call_type"] or "chat"
        price = MODEL_PRICE.get(call_type, MODEL_PRICE["chat"])
        prompt_tokens = item["prompt_tokens"] or 0
        completion_tokens = item["completion_tokens"] or 0
        cost = prompt_tokens / 1000 * price["input_per_1k"] + completion_tokens / 1000 * price["output_per_1k"]
        total_cost += cost
        key = f"{item['model'] or '-'}::{call_type}"
        rows[key] = {
            "model": item["model"] or "",
            "call_type": call_type,
            "calls": item["calls"] or 0,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": item["total_tokens"] or 0,
            "estimated_cost": round(cost, 6),
            "price": price,
        }
    return success_response({
        "estimated_cost": round(total_cost, 6),
        "currency": "CNY",
        "pricing_note": "演示环境按内置单价估算，生产环境应从模型管理的单价字段读取。",
        "items": list(rows.values()),
    })


@extend_schema(tags=["ops"], summary="用量日志列表", responses={200: None})
@api_view(["GET"])
def usage_list(request: Request) -> Response:
    ser = UsageQuerySerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    qs = UsageLog.objects.filter(tenant_id=vd.get("tenant_id") or "default").order_by("-create_date")
    if vd.get("user_id"):
        qs = qs.filter(user_id=vd["user_id"])
    if vd.get("model"):
        qs = qs.filter(model=vd["model"])
    paginator = Paginator(qs, vd["page_size"])
    page_obj = paginator.get_page(vd["page"])
    return success_response({"total": paginator.count, "logs": [_usage_to_dict(row) for row in page_obj.object_list]})


@extend_schema(tags=["ops"], summary="审计日志列表", responses={200: None})
@api_view(["GET"])
def audit_list(request: Request) -> Response:
    ser = AuditQuerySerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    qs = AuditLog.objects.filter(tenant_id=vd.get("tenant_id") or "default").order_by("-create_date")
    if vd.get("user_id"):
        qs = qs.filter(user_id=vd["user_id"])
    if vd.get("action"):
        qs = qs.filter(action=vd["action"])
    if vd.get("resource_type"):
        qs = qs.filter(resource_type=vd["resource_type"])
    paginator = Paginator(qs, vd["page_size"])
    page_obj = paginator.get_page(vd["page"])
    return success_response({"total": paginator.count, "logs": [_audit_to_dict(row) for row in page_obj.object_list]})


@extend_schema(tags=["ops"], summary="质量评估看板", responses={200: None})
@api_view(["GET"])
def quality_summary(request: Request) -> Response:
    tenant_id = request.GET.get("tenant_id") or "default"
    feedback_qs = ConversationFeedback.objects.filter(tenant_id=tenant_id)
    eval_qs = EvaluationResult.objects.filter(tenant_id=tenant_id)
    total_feedback = feedback_qs.count()
    useful = feedback_qs.filter(rating="useful").count()
    useless = feedback_qs.filter(rating="useless").count()
    eval_total = eval_qs.count()
    eval_success = eval_qs.filter(status="success").count()
    avg_score = eval_qs.aggregate(v=Avg("score"))["v"] or 0
    expected_hit = eval_qs.filter(expected_hit="1").count()
    has_ref = eval_qs.filter(has_reference="1").count()
    return success_response({
        "feedback_total": total_feedback,
        "useful": useful,
        "useless": useless,
        "satisfaction_rate": round(useful / total_feedback, 4) if total_feedback else 0,
        "eval_total": eval_total,
        "eval_success": eval_success,
        "avg_score": round(float(avg_score), 4),
        "expected_hit_rate": round(expected_hit / eval_total, 4) if eval_total else 0,
        "reference_rate": round(has_ref / eval_total, 4) if eval_total else 0,
        "by_reason": list(feedback_qs.values("reason").annotate(count=Count("id")).order_by("-count")[:20]),
    })


def _tcp_check(host: str, port: int, timeout: float = 2.0) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"status": "ok", "message": "reachable"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "message": str(exc)}


def _host_port(raw_host: str, default_port: int) -> tuple[str, int]:
    raw = str(raw_host or "").strip()
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or default_port)
        return host, port
    host = raw.split("/")[0] or "127.0.0.1"
    if ":" in host:
        name, port_s = host.rsplit(":", 1)
        if port_s.isdigit():
            return name, int(port_s)
    return host, int(default_port)


def _es_check() -> dict[str, Any]:
    host, port = _host_port(str(getattr(settings, "ES_HOST", "127.0.0.1")), int(getattr(settings, "ES_PORT", 9200)))
    tcp = _tcp_check(host, port)
    if tcp["status"] != "ok":
        return tcp
    try:
        with urlopen(f"http://{host}:{port}/_cluster/health", timeout=2) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        compact = body.replace(" ", "")
        if '"status":"red"' in compact:
            return {"status": "failed", "message": body[:180]}
        return {"status": "ok", "message": "reachable"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "message": str(exc)}


def _record_health_alerts(tenant_id: str, checks: dict[str, Any]) -> None:
    for name, item in checks.items():
        if not isinstance(item, dict) or item.get("status") == "ok":
            continue
        try:
            exists = AlertRecord.objects.filter(tenant_id=tenant_id, alert_type=f"health_{name}", status="open").exists()
            if exists:
                continue
            AlertRecord.objects.create(
                id=get_uuid(),
                tenant_id=tenant_id,
                alert_type=f"health_{name}",
                level="critical",
                title=f"{name} 健康检查失败",
                message=str(item.get("message") or ""),
                detail=item if isinstance(item, dict) else {"message": str(item)},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("write health alert failed name=%s error=%s", name, exc)


@extend_schema(tags=["ops"], summary="系统健康检查", responses={200: None})
@api_view(["GET"])
def health_check(request: Request) -> Response:
    checks: dict[str, Any] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = {"status": "ok", "message": "connected"}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"status": "failed", "message": str(exc)}
    try:
        cache.set("health_check", "1", 5)
        ok = cache.get("health_check") == "1"
        checks["redis_cache"] = {"status": "ok" if ok else "failed", "message": "cache roundtrip" if ok else "cache miss"}
    except Exception as exc:  # noqa: BLE001
        checks["redis_cache"] = {"status": "failed", "message": str(exc)}
    try:
        checks["elasticsearch"] = _es_check()
    except Exception as exc:  # noqa: BLE001
        checks["elasticsearch"] = {"status": "failed", "message": str(exc)}
    try:
        minio_host, minio_port = _host_port(str(settings.MINIO_HOST), 9000)
        checks["minio"] = _tcp_check(minio_host, minio_port)
    except Exception as exc:  # noqa: BLE001
        checks["minio"] = {"status": "failed", "message": str(exc)}
    overall = "ok" if checks and all(
        isinstance(item, dict) and item.get("status") == "ok" for item in checks.values()
    ) else "degraded"
    try:
        tenant_id = request_tenant_id(request) or "default"
        _record_health_alerts(tenant_id, checks)
    except Exception as exc:  # noqa: BLE001
        logger.warning("health alert scan failed error=%s", exc)
    return success_response({"status": overall, "checks": checks})


_SAFETY_RULES = [
    ("prompt_injection", ["忽略以上", "ignore previous", "ignore all previous", "system prompt", "开发者指令", "越狱"]),
    ("secret_leak", ["api_key", "apikey", "密钥", "密码", "token", "authorization"]),
    ("data_exfiltration", ["导出全部", "dump database", "所有用户", "全部数据", "数据库结构"]),
]


@extend_schema(tags=["ops"], summary="内容安全基础检查", responses={200: None})
@api_view(["POST"])
def safety_check(request: Request) -> Response:
    data = request.data if isinstance(request.data, dict) else {}
    text = str(data.get("text") or "")
    lower = text.lower()
    hits = []
    for risk_type, keywords in _SAFETY_RULES:
        matched = [kw for kw in keywords if kw.lower() in lower]
        if matched:
            hits.append({"risk_type": risk_type, "keywords": matched, "level": "high" if risk_type != "secret_leak" else "medium"})
    return success_response({
        "safe": not hits,
        "risk_count": len(hits),
        "hits": hits,
        "suggestion": "存在风险内容，建议人工复核或拒绝执行。" if hits else "未命中基础风险规则。",
    })


@extend_schema(tags=["ops"], summary="告警列表", responses={200: None})
@api_view(["GET"])
def alert_list(request: Request) -> Response:
    tenant_id = request.GET.get("tenant_id") or request_tenant_id(request)
    status = request.GET.get("status") or ""
    qs = AlertRecord.objects.filter(tenant_id=tenant_id).order_by("-create_date")
    if status:
        qs = qs.filter(status=status)
    return success_response([
        {
            "id": row.id,
            "alert_type": row.alert_type,
            "level": row.level,
            "title": row.title,
            "message": row.message or "",
            "status": row.status,
            "detail": row.detail or {},
            "create_date": row.create_date.strftime("%Y-%m-%d %H:%M:%S") if row.create_date else "",
        }
        for row in qs[:100]
    ])


@extend_schema(tags=["ops"], summary="解决告警", responses={200: None})
@api_view(["POST"])
def alert_resolve(request: Request) -> Response:
    data = request.data if isinstance(request.data, dict) else {}
    alert_id = str(data.get("id") or "").strip()
    tenant_id = data.get("tenant_id") or request_tenant_id(request)
    updated = AlertRecord.objects.filter(id=alert_id, tenant_id=tenant_id).update(status="resolved")
    if not updated:
        return error_response("告警不存在。", code=404)
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="resolve", resource_type="alert", resource_id=alert_id)
    return success_response(True)
