import json
from rest_framework import views, permissions, status
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.conf import settings
from .models import Plan, Subscription, UsageRecord
from .serializers import PlanSerializer, SubscriptionSerializer, UsageRecordSerializer
from .services import QuotaEnforcementService, get_billing_adapter
from apps.identity.models import Organization, OrganizationMembership

class PlansListView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        QuotaEnforcementService.get_or_create_default_plan()
        plans = Plan.objects.all().order_by('price_monthly')
        return Response(PlanSerializer(plans, many=True).data)

class SubscriptionDetailView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org_id = request.query_params.get('organization_id')
        if not org_id:
            membership = OrganizationMembership.objects.filter(user=request.user).first()
            if not membership:
                return Response({'error': 'No organization found for user.'}, status=status.HTTP_404_NOT_FOUND)
            org = membership.organization
        else:
            org = get_object_or_404(Organization, id=org_id, memberships__user=request.user)

        sub = QuotaEnforcementService.get_or_create_subscription(org)
        period_key = QuotaEnforcementService.get_current_period_key()
        usage = UsageRecord.objects.filter(organization=org, period_key=period_key)

        total_storage = sum(u.storage_bytes_used for u in usage)
        total_docs = sum(u.documents_count for u in usage)
        total_queries = sum(u.queries_count for u in usage)
        total_tokens = sum(u.tokens_used for u in usage)

        return Response({
            'subscription': SubscriptionSerializer(sub).data,
            'usage': {
                'period_key': period_key,
                'storage_bytes': total_storage,
                'storage_mb': round(total_storage / (1024 * 1024), 2),
                'documents_count': total_docs,
                'queries_count': total_queries,
                'tokens_used': total_tokens,
            },
            'quotas': {
                'max_storage_mb': sub.plan.max_storage_mb if sub.plan else 500,
                'max_documents': sub.plan.max_documents if sub.plan else 50,
                'max_monthly_queries': sub.plan.max_monthly_queries if sub.plan else 500,
            }
        })

    def post(self, request):
        org_id = request.data.get('organization_id')
        plan_slug = request.data.get('plan_slug')
        return_url = request.data.get('return_url', 'http://localhost:3000/settings')

        if not org_id or not plan_slug:
            return Response({'error': 'organization_id and plan_slug are required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Only organization owner or admin can modify subscription
        membership = get_object_or_404(OrganizationMembership, organization_id=org_id, user=request.user)
        if membership.role not in ('owner', 'admin'):
            return Response({'error': 'Only organization owners or administrators can change plans.'}, status=status.HTTP_403_FORBIDDEN)

        adapter = get_billing_adapter()
        try:
            checkout_url = adapter.create_checkout_session(membership.organization, plan_slug, return_url)
            return Response({'checkout_url': checkout_url})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class StripeWebhookView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        payload = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
        webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')

        if not webhook_secret:
            return Response({'message': 'Webhook received (dev bypass)'}, status=status.HTTP_200_OK)

        import stripe
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except Exception as e:
            return Response({'error': f'Invalid webhook signature: {e}'}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event['type']
        data = event['data']['object']

        if event_type == 'checkout.session.completed':
            org_id = data.get('client_reference_id')
            cust_id = data.get('customer')
            sub_id = data.get('subscription')
            if org_id:
                sub = Subscription.objects.filter(organization_id=org_id).first()
                if sub:
                    sub.stripe_customer_id = cust_id or ''
                    sub.stripe_subscription_id = sub_id or ''
                    sub.status = 'active'
                    sub.save()

        elif event_type == 'customer.subscription.deleted':
            sub_id = data.get('id')
            if sub_id:
                Subscription.objects.filter(stripe_subscription_id=sub_id).update(status='canceled')

        return Response({'status': 'success'})
