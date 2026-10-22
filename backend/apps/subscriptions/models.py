import uuid
from django.db import models
from apps.identity.models import Organization
from apps.workspaces.models import Workspace

class Plan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True, default='')
    price_monthly = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    
    # Entitlements & Service Quotas
    max_storage_mb = models.PositiveIntegerField(default=500)
    max_documents = models.PositiveIntegerField(default=50)
    max_monthly_queries = models.PositiveIntegerField(default=500)
    max_workspaces = models.PositiveIntegerField(default=3)
    max_members = models.PositiveIntegerField(default=5)
    
    allow_custom_models = models.BooleanField(default=False)
    allow_ocr_bengali = models.BooleanField(default=True)
    allow_audit_export = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (${self.price_monthly}/mo)"

class Subscription(models.Model):
    STATUS_CHOICES = [
        ('trialing', 'Trialing'),
        ('active', 'Active'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
        ('unpaid', 'Unpaid'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='subscription')
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    
    stripe_customer_id = models.CharField(max_length=100, blank=True, default='')
    stripe_subscription_id = models.CharField(max_length=100, blank=True, default='')
    
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        plan_name = self.plan.name if self.plan else 'No Plan'
        return f"{self.organization.name} -> {plan_name} [{self.status}]"

class UsageRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='usage_records')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, null=True, blank=True, related_name='usage_records')
    
    period_key = models.CharField(max_length=7, db_index=True)  # YYYY-MM e.g. '2026-10'
    storage_bytes_used = models.PositiveBigIntegerField(default=0)
    documents_count = models.PositiveIntegerField(default=0)
    queries_count = models.PositiveIntegerField(default=0)
    ocr_pages_count = models.PositiveIntegerField(default=0)
    tokens_used = models.PositiveBigIntegerField(default=0)
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('organization', 'workspace', 'period_key')

    def __str__(self):
        return f"{self.organization.name} ({self.period_key}): {self.queries_count} queries, {self.documents_count} docs"
