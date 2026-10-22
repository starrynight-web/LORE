from rest_framework import serializers
from .models import Plan, Subscription, UsageRecord

class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            'id', 'name', 'slug', 'description', 'price_monthly',
            'max_storage_mb', 'max_documents', 'max_monthly_queries',
            'max_workspaces', 'max_members', 'allow_custom_models',
            'allow_ocr_bengali', 'allow_audit_export'
        ]

class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    organization_name = serializers.ReadOnlyField(source='organization.name')

    class Meta:
        model = Subscription
        fields = [
            'id', 'organization', 'organization_name', 'plan', 'status',
            'current_period_start', 'current_period_end', 'cancel_at_period_end',
            'created_at', 'updated_at'
        ]

class UsageRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageRecord
        fields = [
            'id', 'organization', 'workspace', 'period_key',
            'storage_bytes_used', 'documents_count', 'queries_count',
            'ocr_pages_count', 'tokens_used', 'updated_at'
        ]
