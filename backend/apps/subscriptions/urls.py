from django.urls import path
from .views import PlansListView, SubscriptionDetailView, StripeWebhookView

urlpatterns = [
    path('plans/', PlansListView.as_view(), name='subscription-plans'),
    path('subscription/', SubscriptionDetailView.as_view(), name='subscription-detail'),
    path('webhooks/stripe/', StripeWebhookView.as_view(), name='stripe-webhook'),
]
