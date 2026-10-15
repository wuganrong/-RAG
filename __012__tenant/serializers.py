"""租户与用户角色接口入参验证。"""

from __future__ import annotations

from rest_framework import serializers


class TenantSaveSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, max_length=64, help_text="租户 ID，留空则新增")
    name = serializers.CharField(max_length=128, help_text="租户名称")
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True, help_text="租户描述")
    status = serializers.ChoiceField(required=False, choices=["0", "1"], default="1", help_text="状态")

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("租户名称不能为空。")
        return value


class TenantIdSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64, help_text="租户 ID")


class UserRoleSaveSerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True, max_length=64, help_text="记录 ID，留空则新增或按租户+用户更新")
    tenant_id = serializers.CharField(required=False, allow_blank=True, default="default", max_length=64, help_text="租户 ID")
    user_id = serializers.CharField(max_length=255, help_text="用户 ID")
    user_name = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=128, help_text="用户名称")
    role = serializers.ChoiceField(choices=["admin", "editor", "viewer"], default="viewer", help_text="角色")
    status = serializers.ChoiceField(required=False, choices=["0", "1"], default="1", help_text="状态")

    def validate_user_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("用户 ID 不能为空。")
        return value


class UserRoleListSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, allow_blank=True, default="", max_length=64, help_text="租户 ID")


class UserRoleIdSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64, help_text="用户角色记录 ID")


class TenantQuotaSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(required=False, allow_blank=True, default="default", max_length=64)
    storage_quota_mb = serializers.IntegerField(required=False, min_value=0, default=10240)
    document_quota = serializers.IntegerField(required=False, min_value=0, default=1000)
    token_quota = serializers.IntegerField(required=False, min_value=0, default=1000000)
    vision_page_quota = serializers.IntegerField(required=False, min_value=0, default=5000)
    model_call_quota = serializers.IntegerField(required=False, min_value=0, default=10000)
    status = serializers.ChoiceField(required=False, choices=["0", "1"], default="1")
