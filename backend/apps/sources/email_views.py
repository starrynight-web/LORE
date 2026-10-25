import time
import secrets
import logging
from typing import Dict, Any
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.core import signing
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import EmailAccountConnection, EmailSyncJob
from .connectors.gmail import GmailConnector, GMAIL_READONLY_SCOPE
from .email_sync import EmailSyncService
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.audit.models import AuditEvent

logger = logging.getLogger(__name__)

OAUTH_STATE_SALT = "lore.email.oauth.csrf"
OAUTH_STATE_MAX_AGE_SECONDS = 600  # 10 minutes


from .serializers import EmailAccountConnectionSerializer, EmailSyncJobSerializer


class EmailConnectionViewSet(viewsets.ModelViewSet):
    """
    CRUD and operational management for connected mailboxes:
    - Lists active connections for the requesting user and authorized workspace
    - Triggers on-demand incremental or full synchronization
    - Performs secure disconnection with documented retention or purge choice
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmailAccountConnectionSerializer

    def get_queryset(self):
        user = self.request.user
        workspace_id = self.request.query_params.get('workspace')
        qs = EmailAccountConnection.objects.all()

        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)

        # Enforce workspace isolation
        # Users can see their own connections; workspace admins can see all connections in the workspace
        user_admin_ws = WorkspaceMembership.objects.filter(
            user=user, role__in=['workspace_admin', 'owner', 'admin']
        ).values_list('workspace_id', flat=True)

        return qs.filter(models_q(user=user) | models_q(workspace_id__in=user_admin_ws)).distinct()

    def list(self, request, *args, **kwargs):
        workspace_id = request.query_params.get('workspace')
        if not workspace_id:
            return Response({'error': 'workspace query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Verify membership
        get_object_or_404(WorkspaceMembership, workspace_id=workspace_id, user=request.user)

        connections = self.get_queryset().filter(workspace_id=workspace_id)
        return Response(EmailAccountConnectionSerializer(connections, many=True).data)

    def retrieve(self, request, pk=None):
        conn = get_object_or_404(EmailAccountConnection, id=pk)
        self._check_access(conn, request.user)
        return Response(EmailAccountConnectionSerializer(conn).data)

    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """Triggers manual synchronization for this connected email account."""
        conn = get_object_or_404(EmailAccountConnection, id=pk)
        self._check_access(conn, request.user)

        full_sync = request.data.get('full_sync', False)
        max_messages = int(request.data.get('max_messages', 50))

        job = EmailSyncService.trigger_sync(
            connection=conn,
            user=request.user,
            max_messages=max_messages,
            full_sync=full_sync
        )

        return Response({
            'message': 'Synchronization initiated successfully.',
            'job_id': str(job.id),
            'status': job.status,
            'messages_detected': job.messages_detected,
            'messages_imported': job.messages_imported,
            'attachments_imported': job.attachments_imported,
            'errors': job.errors,
            'duration_ms': job.duration_ms
        })

    @action(detail=True, methods=['post'])
    def disconnect(self, request, pk=None):
        """Disconnects the email account with documented retention or purge choice."""
        conn = get_object_or_404(EmailAccountConnection, id=pk)
        self._check_access(conn, request.user)

        retain_content = request.data.get('retain_content', True)
        if isinstance(retain_content, str):
            retain_content = retain_content.lower() in ('true', '1', 'yes')

        result = EmailSyncService.disconnect_connection(
            connection=conn,
            user=request.user,
            retain_content=retain_content
        )

        return Response(result)

    @action(detail=True, methods=['get'])
    def jobs(self, request, pk=None):
        """Lists recent sync jobs for this connection."""
        conn = get_object_or_404(EmailAccountConnection, id=pk)
        self._check_access(conn, request.user)

        jobs = conn.sync_jobs.all()[:20]
        return Response(EmailSyncJobSerializer(jobs, many=True).data)

    def _check_access(self, connection: EmailAccountConnection, user):
        """Ensures requesting user is the connection owner or a workspace admin."""
        if connection.user == user:
            return
        is_admin = WorkspaceMembership.objects.filter(
            workspace=connection.workspace,
            user=user,
            role__in=['workspace_admin', 'owner', 'admin']
        ).exists()
        if not is_admin:
            raise PermissionDenied("You do not have permission to manage this email account connection.")


def models_q(**kwargs):
    from django.db.models import Q
    return Q(**kwargs)


class EmailOAuthAuthorizeView(APIView):
    """
    Step 2: Initiates OAuth authorization flow with CSRF-protected signed state parameter.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        workspace_id = request.query_params.get('workspace') or request.query_params.get('workspace_id')
        provider = request.query_params.get('provider', 'gmail').lower()

        if not workspace_id:
            return Response({'error': 'workspace query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        workspace = get_object_or_404(Workspace, id=workspace_id, memberships__user=request.user)

        if provider != 'gmail':
            return Response({'error': f"Provider '{provider}' is not supported. Supported providers: 'gmail'."}, status=status.HTTP_400_BAD_REQUEST)

        client_id = getattr(settings, 'GMAIL_CLIENT_ID', '') or request.query_params.get('client_id', '')
        redirect_uri = getattr(settings, 'GMAIL_REDIRECT_URI', '') or request.query_params.get('redirect_uri', 'http://127.0.0.1:8000/api/v1/sources/email/oauth/callback/')

        # Cryptographically sign the state token with HMAC-SHA256
        state_payload = {
            'workspace_id': str(workspace.id),
            'user_id': request.user.id,
            'provider': provider,
            'ts': int(time.time()),
            'nonce': secrets.token_hex(16)
        }
        signed_state = signing.dumps(state_payload, salt=OAUTH_STATE_SALT)

        auth_url = GmailConnector.build_authorization_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=signed_state
        )

        return Response({
            'provider': provider,
            'authorization_url': auth_url,
            'state': signed_state,
            'scope': GMAIL_READONLY_SCOPE,
            'redirect_uri': redirect_uri,
        })


class EmailOAuthCallbackView(APIView):
    """
    Step 2: Receives OAuth callback, validates state signature, exchanges code,
    encrypts tokens, and registers the EmailAccountConnection.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return self._handle_callback(request)

    def post(self, request):
        return self._handle_callback(request)

    def _handle_callback(self, request):
        code = request.query_params.get('code') or request.data.get('code')
        state = request.query_params.get('state') or request.data.get('state')
        error = request.query_params.get('error') or request.data.get('error')

        if error:
            logger.warning("OAuth authorization rejected by provider: %s", error)
            return Response({'error': f"OAuth provider returned an error: {error}"}, status=status.HTTP_400_BAD_REQUEST)

        if not code or not state:
            return Response({'error': "Both 'code' and 'state' parameters are required."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Validate signed state token (CSRF & Tamper protection)
        try:
            state_data = signing.loads(state, salt=OAUTH_STATE_SALT, max_age=OAUTH_STATE_MAX_AGE_SECONDS)
        except signing.SignatureExpired:
            return Response({'error': 'OAuth state expired. Please initiate authorization again.'}, status=status.HTTP_400_BAD_REQUEST)
        except signing.BadSignature:
            return Response({'error': 'Invalid or tampered OAuth state parameter.'}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({'error': f'State validation error: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

        workspace_id = state_data.get('workspace_id')
        user_id = state_data.get('user_id')
        provider = state_data.get('provider', 'gmail')

        from django.contrib.auth.models import User
        user = get_object_or_404(User, id=user_id)
        workspace = get_object_or_404(Workspace, id=workspace_id)

        # 2. Exchange authorization code for tokens
        client_id = getattr(settings, 'GMAIL_CLIENT_ID', '') or request.data.get('client_id', '')
        client_secret = getattr(settings, 'GMAIL_CLIENT_SECRET', '') or request.data.get('client_secret', '')
        redirect_uri = getattr(settings, 'GMAIL_REDIRECT_URI', '') or request.data.get('redirect_uri', 'http://127.0.0.1:8000/api/v1/sources/email/oauth/callback/')

        try:
            token_data = GmailConnector.exchange_code_for_tokens(
                code=code,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri
            )
            access_token = token_data.get('access_token', '')
            refresh_token = token_data.get('refresh_token', '')
            expires_in = token_data.get('expires_in', 3600)

            # 3. Retrieve user email address
            profile = GmailConnector.fetch_user_profile(access_token)
            email_address = profile.get('emailAddress', 'user@gmail.com')

            # 4. Create or update EmailAccountConnection with encrypted tokens
            from django.utils import timezone as dj_timezone
            conn, created = EmailAccountConnection.objects.get_or_create(
                workspace=workspace,
                user=user,
                email_address=email_address,
                defaults={
                    'organization': workspace.organization,
                    'provider': provider,
                    'account_name': email_address.split('@')[0],
                    'status': 'connected',
                    'scopes': [GMAIL_READONLY_SCOPE]
                }
            )

            conn.set_tokens(access_token=access_token, refresh_token=refresh_token)
            conn.token_expires_at = dj_timezone.now() + dj_timezone.timedelta(seconds=expires_in)
            conn.status = 'connected'
            conn.last_error = ''
            conn.save()

            # 5. Audit Event
            AuditEvent.objects.create(
                organization=workspace.organization,
                workspace=workspace,
                user=user,
                event_type='document_uploaded',
                target_type='email_account_connection',
                target_id=str(conn.id),
                details={
                    'action': 'email_account_connected',
                    'email_address': email_address,
                    'provider': provider,
                    'created': created
                }
            )

            # If browser GET callback, optionally redirect to frontend or return JSON
            frontend_redirect = request.query_params.get('frontend_redirect')
            if frontend_redirect and request.method == 'GET':
                return redirect(f"{frontend_redirect}?email_connected=true&connection_id={conn.id}")

            return Response({
                'success': True,
                'connection_id': str(conn.id),
                'email_address': email_address,
                'provider': provider,
                'status': conn.status,
                'created': created,
                'message': f"Successfully connected email account '{email_address}'."
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        except Exception as e:
            logger.exception("OAuth callback processing failed: %s", e)
            return Response({'error': f"OAuth authorization failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
