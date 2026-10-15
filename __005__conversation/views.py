"""会话（Conversation）接口视图。"""

from __future__ import annotations

# 1. Python 标准库
import json
import time

# 2. 第三方库
from django.db.models import DateTimeField
from django.http import StreamingHttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.assistant.service import AssistantService
from __001__rag.models import Conversation, ConversationFeedback, Knowledgebase
from __001__rag.ops import request_tenant_id, request_user_id, write_audit, write_usage
from __001__rag.utils import error_response, success_response
from __001__rag.utils.ids import get_uuid
from __001__rag.utils.time import format_datetime
from __005__conversation.utils import chunks_format, completion_stream_generator, completion_with_all_stream_generator, completion_with_model_stream_generator, conversation_to_dict

from .serializers import (
    ConversationCompletionSerializer,
    ConversationCompletionWithAllSerializer,
    ConversationCompletionWithModelSerializer,
    ConversationDeleteMsgSerializer,
    ConversationFeedbackListSerializer,
    ConversationFeedbackSerializer,
    ConversationExportSerializer,
    ConversationGetSerializer,
    ConversationListSerializer,
    ConversationRmSerializer,
    ConversationSetSerializer,
)

_CONVERSATION_TAG = ["conversation"]
_ASSISTANT_KEY = "chat"


# =============================================================================
# 视图函数
# =============================================================================


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="获取会话详情",
    description="根据 conversation_id 获取单个会话的完整信息，包含权限校验和 avatar。",
    parameters=[
        OpenApiParameter("conversation_id", OpenApiTypes.STR, required=True, description="会话 ID"),
        OpenApiParameter("user_id", OpenApiTypes.STR, required=False, description="用户 ID"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def conversation_get(request: Request) -> Response:
    """GET /v1/conversation/get — 获取会话详情。"""
    ser = ConversationGetSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    conv_id: str = ser.validated_data["conversation_id"]
    tenant_id: str = ser.validated_data.get("tenant_id") or request_tenant_id(request)
    user_id: str = ser.validated_data.get("user_id", "")

    try:
        conv = Conversation.objects.get(id=conv_id, tenant_id=tenant_id)
    except Conversation.DoesNotExist:
        logger.info("会话不存在 conv_id={}", conv_id)
        return error_response("会话不存在", code=404)

    if user_id and conv.user_id != user_id:
        return error_response("无权访问该会话", code=403)

    # 获取 assistant 名称作为 avatar
    avatar = ""
    try:
        assistant_cfg = AssistantService.get_config(_ASSISTANT_KEY)
        avatar = assistant_cfg.assistant_name or ""
    except Exception:
        logger.info("获取 assistant 配置失败，使用空 avatar")

    conv_dict = conversation_to_dict(conv)
    conv_dict["avatar"] = avatar

    return success_response(conv_dict)


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="查询会话列表",
    description="根据 user_id 查询会话列表，按创建时间降序排列。",
    parameters=[
        OpenApiParameter("user_id", OpenApiTypes.STR, required=True, description="用户 ID"),
        OpenApiParameter("orderby", OpenApiTypes.STR, required=False, description="排序字段，默认 create_date"),
        OpenApiParameter("desc", OpenApiTypes.BOOL, required=False, description="是否降序，默认 true"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def conversation_list(request: Request) -> Response:
    """GET /v1/conversation/list — 查询会话列表。"""
    ser = ConversationListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    user_id: str = vd["user_id"]
    tenant_id: str = vd.get("tenant_id") or request_tenant_id(request)
    orderby: str = vd["orderby"]
    desc: bool = vd["desc"]

    qs = Conversation.objects.filter(user_id=user_id, tenant_id=tenant_id)
    valid_fields = {f.name for f in Conversation._meta.get_fields()}
    if orderby not in valid_fields:
        orderby = "create_date"

    field = Conversation._meta.get_field(orderby)
    if isinstance(field, DateTimeField):
        if desc:
            qs = qs.order_by(f"-{orderby}")
        else:
            qs = qs.order_by(orderby)
    else:
        qs = qs.order_by("-create_date")

    conversations = [conversation_to_dict(c) for c in qs]
    return success_response(conversations)


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="重命名会话",
    description="根据 conversation_id 更新会话标题。",
    request=ConversationSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def conversation_set(request: Request) -> Response:
    """POST /v1/conversation/set — 重命名会话。"""
    ser = ConversationSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    conv_id: str = vd["conversation_id"]
    tenant_id: str = vd.get("tenant_id") or request_tenant_id(request)
    user_id: str = vd.get("user_id", "")

    try:
        conv = Conversation.objects.get(id=conv_id, tenant_id=tenant_id)
    except Conversation.DoesNotExist:
        logger.info("会话不存在 conv_id={}", conv_id)
        return error_response("会话不存在", code=404)

    if user_id and conv.user_id != user_id:
        return error_response("无权修改该会话", code=403)

    conv.name = vd["name"]
    conv.save()
    write_audit(tenant_id=tenant_id, user_id=user_id or request_user_id(request), action="rename", resource_type="conversation", resource_id=conv.id, detail={"name": conv.name})

    return success_response(conversation_to_dict(conv))


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="删除会话",
    description="批量删除会话，逐个校验 user_id 所有权。",
    request=ConversationRmSerializer,
    responses={200: None},
)
@api_view(["POST"])
def conversation_rm(request: Request) -> Response:
    """POST /v1/conversation/rm — 删除会话。"""
    ser = ConversationRmSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    conv_ids: list[str] = vd["conversation_ids"]
    tenant_id: str = vd.get("tenant_id") or request_tenant_id(request)
    user_id: str = vd.get("user_id", "")

    for cid in conv_ids:
        try:
            conv = Conversation.objects.get(id=cid, tenant_id=tenant_id)
        except Conversation.DoesNotExist:
            logger.info("会话不存在 conv_id={}", cid)
            return error_response("会话不存在", code=404)

        if user_id and conv.user_id != user_id:
            return error_response("无权删除该会话", code=403)

        conv.delete()
        write_audit(tenant_id=tenant_id, user_id=user_id or request_user_id(request), action="delete", resource_type="conversation", resource_id=cid)
        logger.info("会话删除成功 conv_id={}", cid)

    return success_response(True)


@extend_schema(tags=_CONVERSATION_TAG, summary="导出会话", responses={200: None})
@api_view(["GET"])
def conversation_export(request: Request) -> Response:
    ser = ConversationExportSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    conv_id = vd["conversation_id"]
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    user_id = vd.get("user_id") or ""
    try:
        conv = Conversation.objects.get(id=conv_id, tenant_id=tenant_id)
    except Conversation.DoesNotExist:
        return error_response("会话不存在", code=404)
    if user_id and conv.user_id != user_id:
        return error_response("无权导出该会话", code=403)

    data = conversation_to_dict(conv)
    if vd.get("export_format") == "json":
        payload = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        lines = [f"# {data.get('name') or conv.id}", "", f"- 会话ID：{conv.id}", f"- 用户：{conv.user_id or ''}", ""]
        for msg in data.get("message", []):
            role = "用户" if msg.get("role") == "user" else "助手"
            lines.extend([f"## {role}", "", str(msg.get("content") or ""), ""])
        payload = "\n".join(lines)
    write_audit(tenant_id=tenant_id, user_id=user_id or request_user_id(request), action="export", resource_type="conversation", resource_id=conv.id)
    return success_response({"conversation_id": conv.id, "format": vd.get("export_format"), "content": payload})


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="删除会话消息",
    description="删除指定消息及其紧随的 assistant 回复，同时清理对应的 reference 条目。",
    request=ConversationDeleteMsgSerializer,
    responses={200: None},
)
@api_view(["POST"])
def conversation_delete_msg(request: Request) -> Response:
    """POST /v1/conversation/delete_msg — 删除会话消息。"""
    ser = ConversationDeleteMsgSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    conv_id: str = vd["conversation_id"]
    tenant_id: str = vd.get("tenant_id") or request_tenant_id(request)
    message_id: str = vd["message_id"]

    try:
        conv = Conversation.objects.get(id=conv_id, tenant_id=tenant_id)
    except Conversation.DoesNotExist:
        logger.info("会话不存在 conv_id={}", conv_id)
        return error_response("会话不存在", code=404)

    conv_dict = conversation_to_dict(conv)
    messages: list[dict] = conv_dict["message"]
    references: list[dict] = conv_dict["reference"]

    for i, msg in enumerate(messages):
        if message_id != msg.get("id", ""):
            continue

        if i + 1 >= len(messages):
            messages.pop(i)
        else:
            next_is_assistant = messages[i + 1].get("role", "") == "assistant"
            drop_count = 2 if next_is_assistant else 1
            messages[i : i + drop_count] = []

        # 清理 reference：优先按 message_id 精确匹配，降级按位置匹配
        found_index = next(
            (index for index, item in enumerate(references) if item.get("message_id") == message_id),
            None,
        )
        if found_index is not None:
            references.pop(found_index)
        else:
            # 每个 user+assistant 轮次对应一条 reference，user 消息在 messages 中的索引 i
            # 满足 i = 2 * round_index（0-based），因此 reference 索引 = i // 2
            ref_index = i // 2
            if ref_index < len(references):
                references.pop(ref_index)
        break

    conv.message = json.dumps(messages, ensure_ascii=False)
    conv.reference = json.dumps(references, ensure_ascii=False)
    conv.save()

    return success_response(conversation_to_dict(conv))


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="提交回答反馈",
    description="对某次 assistant 回答提交有用/无用反馈；同一用户对同一消息重复提交会覆盖。",
    request=ConversationFeedbackSerializer,
    responses={200: None},
)
@api_view(["POST"])
def conversation_feedback(request: Request) -> Response:
    ser = ConversationFeedbackSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    conv_id = vd["conversation_id"]
    message_id = vd["message_id"]
    user_id = vd.get("user_id") or ""
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)

    if not Conversation.objects.filter(id=conv_id, tenant_id=tenant_id).exists():
        return error_response("会话不存在。", code=404)

    feedback, _ = ConversationFeedback.objects.get_or_create(
        tenant_id=tenant_id,
        conversation_id=conv_id,
        message_id=message_id,
        user_id=user_id,
        defaults={"id": get_uuid()},
    )
    feedback.rating = vd["rating"]
    feedback.reason = vd.get("reason") or ""
    feedback.comment = vd.get("comment") or ""
    feedback.save()
    write_audit(tenant_id=tenant_id, user_id=user_id, action="feedback", resource_type="conversation", resource_id=conv_id, detail={"message_id": message_id, "rating": feedback.rating, "reason": feedback.reason})
    return success_response(_feedback_to_dict(feedback))


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="查询回答反馈",
    parameters=[
        OpenApiParameter("conversation_id", OpenApiTypes.STR, required=False, description="会话 ID"),
        OpenApiParameter("user_id", OpenApiTypes.STR, required=False, description="用户 ID"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def conversation_feedback_list(request: Request) -> Response:
    ser = ConversationFeedbackListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    qs = ConversationFeedback.objects.all().order_by("-create_date")
    qs = qs.filter(tenant_id=vd.get("tenant_id") or request_tenant_id(request))
    if vd.get("conversation_id"):
        qs = qs.filter(conversation_id=vd["conversation_id"])
    if vd.get("user_id"):
        qs = qs.filter(user_id=vd["user_id"])
    return success_response([_feedback_to_dict(item) for item in qs[:200]])


def _feedback_to_dict(feedback: ConversationFeedback) -> dict:
    return {
        "id": feedback.id,
        "conversation_id": feedback.conversation_id,
        "message_id": feedback.message_id,
        "user_id": feedback.user_id,
        "tenant_id": getattr(feedback, "tenant_id", "default") or "default",
        "rating": feedback.rating,
        "reason": feedback.reason,
        "comment": feedback.comment,
        "create_date": format_datetime(feedback.create_date),
        "update_date": format_datetime(feedback.update_date),
    }


# =============================================================================
# Completion 视图
# =============================================================================


def _prepare_completion_conv(
    conv_id: str,
    messages: list[dict],
    *,
    user_id: str = "",
    tenant_id: str = "default",
    name: str = "",
    model: str = "",
) -> Conversation:
    """按 conversation_id 获取或创建会话，并预处理消息与 reference。"""
    try:
        conv = Conversation.objects.get(id=conv_id, tenant_id=tenant_id)
    except Conversation.DoesNotExist:
        conv = Conversation.objects.create(
            id=conv_id,
            name=name or "New conversation",
            model=model or "",
            message=json.dumps(messages, ensure_ascii=False),
            reference=json.dumps([], ensure_ascii=False),
            user_id=user_id,
            tenant_id=tenant_id,
        )
        logger.info("会话创建成功 conv_id={} user_id={}", conv.id, user_id)
        return conv

    if user_id and conv.user_id and conv.user_id != user_id:
        raise PermissionError("无权访问该会话")

    if name:
        conv.name = name
    if model:
        conv.model = model

    conv.message = json.dumps(messages, ensure_ascii=False)
    conv.reference = conv.reference or json.dumps([], ensure_ascii=False)

    try:
        refs = json.loads(conv.reference) if isinstance(conv.reference, str) else (conv.reference or [])
        for ref in refs:
            if isinstance(ref, list):
                continue
            ref["chunks"] = chunks_format(ref)
        conv.reference = json.dumps(refs, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        logger.info("[DEGRADE] 会话引用数据解析失败 conv_id={}", conv.id)

    return conv


def _build_completion_response(conv: Conversation, messages: list[dict], assistant_cfg, **kwargs):
    """构建 SSE StreamingHttpResponse。"""
    resp = StreamingHttpResponse(
        completion_stream_generator(conv, messages, assistant_cfg, **kwargs),
        content_type="text/event-stream",
    )
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


def _validate_completion_kb_ids(kb_ids: list[str], tenant_id: str = "default") -> Response | None:
    """校验本次问答指定的知识库是否存在并启用。"""
    if not kb_ids:
        return None
    valid_ids = set(
        Knowledgebase.objects.filter(id__in=kb_ids, tenant_id=tenant_id, status="1").values_list("id", flat=True)
    )
    invalid_ids = [kb_id for kb_id in kb_ids if kb_id not in valid_ids]
    if invalid_ids:
        return error_response(f"知识库不存在或未启用: {', '.join(invalid_ids)}", code=400)
    return None


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="对话补全（流式 SSE）",
    description=(
        "统一的对话补全接口，返回 SSE 流式响应。\n\n"
        "按 conversation_id 自动创建或更新会话记录，再执行检索与流式生成。\n"
        "可通过 model_name 覆盖 assistant 默认模型，use_all_kbs 开启全知识库检索。"
    ),
    request=ConversationCompletionSerializer,
    responses={200: None},
)
@api_view(["POST"])
def conversation_completion(request: Request):
    """POST /v1/conversation/completion — 对话补全（流式 SSE）。"""
    ser = ConversationCompletionSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    started = time.perf_counter()
    conv_id: str = vd["conversation_id"]
    tenant_id: str = vd.get("tenant_id") or request_tenant_id(request)
    messages: list[dict] = vd["messages"]
    kb_ids: list[str] = vd.get("kb_ids") or []

    kb_error = _validate_completion_kb_ids(kb_ids, tenant_id)
    if kb_error is not None:
        return kb_error

    try:
        conv = _prepare_completion_conv(
            conv_id,
            messages,
            tenant_id=tenant_id,
            user_id=vd.get("user_id", ""),
            name=vd.get("name", ""),
            model=vd.get("model", ""),
        )
    except PermissionError as e:
        return error_response(str(e), code=403)

    # 助理可由请求指定；不传或传空则回退到默认 chat 助理
    assistant_key: str = vd.get("assistant_key") or _ASSISTANT_KEY
    try:
        assistant_cfg = AssistantService.get_config(assistant_key)
    except Exception as e:
        logger.info("获取 assistant 配置失败 assistant_key={} error={}", assistant_key, e)
        return error_response(f"助理配置不存在或已禁用：{assistant_key}", code=500)

    write_usage(
        tenant_id=tenant_id,
        user_id=vd.get("user_id", "") or request_user_id(request),
        conversation_id=conv_id,
        kb_ids=kb_ids,
        model=vd.get("model", "") or getattr(assistant_cfg, "model_name", ""),
        call_type="chat",
        prompt_tokens=sum(len(str(m.get("content", ""))) for m in messages),
        duration_ms=int((time.perf_counter() - started) * 1000),
        status="accepted",
    )
    return _build_completion_response(
        conv,
        messages,
        assistant_cfg,
        kb_ids=kb_ids or None,
        model_name=vd.get("model") or None,
    )


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="模型对比对话补全（流式 SSE）",
    description="指定模型与参数进行对话补全，返回 SSE 流式响应。不保存会话记录。",
    request=ConversationCompletionWithModelSerializer,
    responses={200: None},
)
@api_view(["POST"])
def conversation_completion_with_model(request: Request):
    """POST /v1/conversation/completion_with_model — 模型对比对话补全（流式 SSE）。"""
    ser = ConversationCompletionWithModelSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    messages: list[dict] = vd["messages"]

    try:
        assistant_cfg = AssistantService.get_config(_ASSISTANT_KEY)
    except Exception as e:
        logger.info("获取 assistant 配置失败 error={}", e)
        return error_response("助理配置不存在或已禁用", code=500)

    resp = StreamingHttpResponse(
        completion_with_model_stream_generator(
            messages,
            assistant_cfg,
            model_name=vd["model_name"],
            temperature=vd["temperature"],
            top_p=vd["top_p"],
            enable_thinking=vd["enable_thinking"],
        ),
        content_type="text/event-stream",
    )
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@extend_schema(
    tags=_CONVERSATION_TAG,
    summary="多参数对话补全（流式 SSE）",
    description="支持系统提示词与检索参数全覆盖的对话补全，返回 SSE 流式响应。不保存会话记录。",
    request=ConversationCompletionWithAllSerializer,
    responses={200: None},
)
@api_view(["POST"])
def conversation_completion_with_all(request: Request):
    """POST /v1/conversation/completion_with_all — 多参数对话补全（流式 SSE）。"""
    ser = ConversationCompletionWithAllSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    messages: list[dict] = vd["messages"]

    try:
        assistant_cfg = AssistantService.get_config(_ASSISTANT_KEY)
    except Exception as e:
        logger.info("获取 assistant 配置失败 error={}", e)
        return error_response("助理配置不存在或已禁用", code=500)

    resp = StreamingHttpResponse(
        completion_with_all_stream_generator(
            messages,
            assistant_cfg,
            system_prompt=vd.get("system_prompt") or None,
            model_name=vd["model_name"],
            temperature=vd["temperature"],
            top_p=vd["top_p"],
            enable_thinking=vd["enable_thinking"],
            top_k=vd["top_k"],
            similarity_threshold=vd["similarity_threshold"],
            vector_similarity_weight=vd["vector_similarity_weight"],
        ),
        content_type="text/event-stream",
    )
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp
