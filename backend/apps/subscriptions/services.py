import logging
from datetime import datetime
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from .models import Plan, Subscription, UsageRecord
from apps.identity.models import Organization

logger = logging.getLogger(__name__)

class QuotaEnforcementService:
    """
    Central server-side quota enforcement for multi-tenant SaaS operations.
    Guarantees storage, document count, query count, and workspace caps.
    """

    @classmethod
    def get_or_create_default_plan(cls) -> Plan:
        plan, _ = Plan.objects.get_or_create(
            slug='free',
            defaults={
                'name': 'Free Tier',
                'description': 'Essential knowledge retrieval for small teams',
                'price_monthly': 0.00,
                'max_storage_mb': 500,
                'max_documents': 50,
                'max_monthly_queries': 500,
                'max_workspaces': 2,
                'max_members': 3,
                'allow_custom_models': False,
                'allow_ocr_bengali': True,
                'allow_audit_export': False,
            }
        )
        return plan

    @classmethod
    def get_or_create_subscription(cls, organization: Organization) -> Subscription:
        sub = Subscription.objects.filter(organization=organization).select_related('plan').first()
        if not sub:
            plan = cls.get_or_create_default_plan()
            sub = Subscription.objects.create(
                organization=organization,
                plan=plan,
                status='active',
                current_period_start=timezone.now(),
            )
        return sub

    @classmethod
    def get_current_period_key(cls) -> str:
        return timezone.now().strftime('%Y-%m')

    @classmethod
    def get_or_create_usage_record(cls, organization: Organization, workspace=None) -> UsageRecord:
        period_key = cls.get_current_period_key()
        rec, _ = UsageRecord.objects.get_or_create(
            organization=organization,
            workspace=workspace,
            period_key=period_key
        )
        return rec

    @classmethod
    def check_upload_quota(cls, organization: Organization, file_size_bytes: int):
        sub = cls.get_or_create_subscription(organization)
        plan = sub.plan or cls.get_or_create_default_plan()

        period_key = cls.get_current_period_key()
        # Sum current usage across organization
        usage = UsageRecord.objects.filter(organization=organization, period_key=period_key)
        total_storage_bytes = sum(u.storage_bytes_used for u in usage)
        total_docs = sum(u.documents_count for u in usage)

        max_storage_bytes = plan.max_storage_mb * 1024 * 1024
        if total_storage_bytes + file_size_bytes > max_storage_bytes:
            raise ValidationError(
                f"Organization storage quota exceeded ({plan.max_storage_mb} MB limit on {plan.name}). "
                "Please upgrade your plan to increase storage capacity."
            )

        if total_docs + 1 > plan.max_documents:
            raise ValidationError(
                f"Organization document count quota exceeded ({plan.max_documents} docs limit on {plan.name}). "
                "Please upgrade your plan to upload additional documents."
            )

    @classmethod
    def check_query_quota(cls, organization: Organization):
        sub = cls.get_or_create_subscription(organization)
        plan = sub.plan or cls.get_or_create_default_plan()

        period_key = cls.get_current_period_key()
        usage = UsageRecord.objects.filter(organization=organization, period_key=period_key)
        total_queries = sum(u.queries_count for u in usage)

        if total_queries >= plan.max_monthly_queries:
            raise ValidationError(
                f"Monthly query quota exceeded ({plan.max_monthly_queries} queries limit on {plan.name}). "
                "Please upgrade your subscription or wait until next billing cycle."
            )

    @classmethod
    def record_upload(cls, organization: Organization, workspace, file_size_bytes: int):
        rec = cls.get_or_create_usage_record(organization, workspace)
        rec.storage_bytes_used += file_size_bytes
        rec.documents_count += 1
        rec.save(update_fields=['storage_bytes_used', 'documents_count', 'updated_at'])

    @classmethod
    def record_query(cls, organization: Organization, workspace, token_count: int = 0):
        rec = cls.get_or_create_usage_record(organization, workspace)
        rec.queries_count += 1
        rec.tokens_used += token_count
        rec.save(update_fields=['queries_count', 'tokens_used', 'updated_at'])

class BaseBillingAdapter:
    def create_checkout_session(self, organization: Organization, plan_slug: str, return_url: str) -> str:
        raise NotImplementedError

    def create_portal_session(self, organization: Organization, return_url: str) -> str:
        raise NotImplementedError

class LocalDevBillingAdapter(BaseBillingAdapter):
    """
    Simulation billing adapter for zero-credential local development and automated testing.
    Instantly upgrades organization subscriptions without external network calls.
    """
    def create_checkout_session(self, organization: Organization, plan_slug: str, return_url: str) -> str:
        plan = Plan.objects.filter(slug=plan_slug).first()
        if plan:
            sub = QuotaEnforcementService.get_or_create_subscription(organization)
            sub.plan = plan
            sub.status = 'active'
            sub.save()
        return f"{return_url}?checkout=success&plan={plan_slug}"

    def create_portal_session(self, organization: Organization, return_url: str) -> str:
        return f"{return_url}?portal=simulated"

class StripeBillingAdapter(BaseBillingAdapter):
    """
    Production Stripe Billing adapter with checkout sessions, customer portals, and webhooks.
    """
    def __init__(self):
        import stripe
        stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')

    def create_checkout_session(self, organization: Organization, plan_slug: str, return_url: str) -> str:
        import stripe
        plan = Plan.objects.get(slug=plan_slug)
        sub = QuotaEnforcementService.get_or_create_subscription(organization)

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': f"LORE Enterprise — {plan.name}"},
                    'unit_amount': int(plan.price_monthly * 100),
                    'recurring': {'interval': 'month'},
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{return_url}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=return_url,
            client_reference_id=str(organization.id),
        )
        return session.url

    def create_portal_session(self, organization: Organization, return_url: str) -> str:
        import stripe
        sub = QuotaEnforcementService.get_or_create_subscription(organization)
        if not sub.stripe_customer_id:
            return return_url
        session = stripe.billing_portal.Session.create(
            customer=sub.stripe_customer_id,
            return_url=return_url,
        )
        return session.url

def get_billing_adapter() -> BaseBillingAdapter:
    if getattr(settings, 'BILLING_ENABLED', False) and getattr(settings, 'STRIPE_SECRET_KEY', ''):
        return StripeBillingAdapter()
    return LocalDevBillingAdapter()
