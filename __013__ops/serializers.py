"""用量统计与审计日志接口入参。"""

from __future__ import annotations

from rest_framework import serializers


class UsageQuerySerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="default", allow_blank=True, max_length=64)
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    model = serializers.CharField(required=False, allow_blank=True, max_length=255)
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=50, min_value=1, max_value=200)


class AuditQuerySerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, default="default", allow_blank=True, max_length=64)
    user_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    action = serializers.CharField(required=False, allow_blank=True, max_length=64)
    resource_type = serializers.CharField(required=False, allow_blank=True, max_length=64)
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=50, min_value=1, max_value=200)
