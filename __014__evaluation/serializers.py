"""评测问题集接口入参。"""

from __future__ import annotations

from rest_framework import serializers


class EvalQuestionListSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="default", allow_blank=True, max_length=64)
    kb_id = serializers.CharField(required=False, allow_blank=True, max_length=64)


class EvalQuestionSaveSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    tenant_id = serializers.CharField(required=False, default="default", allow_blank=True, max_length=64)
    kb_id = serializers.CharField(max_length=64)
    question = serializers.CharField()
    expected_answer = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    tags = serializers.ListField(required=False, child=serializers.CharField(), default=list)
    status = serializers.ChoiceField(required=False, choices=["0", "1"], default="1")


class EvalQuestionIdSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64)


class EvalRunSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="default", allow_blank=True, max_length=64)
    kb_id = serializers.CharField(max_length=64)
    top_n = serializers.IntegerField(required=False, default=6, min_value=1, max_value=20)


class EvalResultListSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="default", allow_blank=True, max_length=64)
    kb_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    question_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
