import logging
from rest_framework.authentication import BaseAuthentication
from django.contrib.auth.models import User
from django.conf import settings

logger = logging.getLogger(__name__)

class GuestModeAuthentication(BaseAuthentication):
    """
    Seamless Guest Mode Authentication:
    When GUEST_MODE_ENABLED is True, any request arriving without an Authorization header
    is automatically bound to the demo administrator persona (admin@northstar.demo).
    This allows unauthenticated visitors to explore the entire knowledge workspace,
    document library, OCR studio, and governed RAG without an intrusive login wall.
    """

    def authenticate(self, request):
        guest_enabled = getattr(settings, 'GUEST_MODE_ENABLED', True)
        if not guest_enabled:
            return None

        # If request provides an Authorization token, let TokenAuthentication handle it
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if auth_header:
            return None

        # Check for demo admin user
        guest_user = User.objects.filter(username='admin@northstar.demo').first()
        if not guest_user:
            guest_user = User.objects.filter(is_staff=True).first()
        if not guest_user:
            guest_user = User.objects.first()

        if guest_user:
            return (guest_user, None)

        return None
