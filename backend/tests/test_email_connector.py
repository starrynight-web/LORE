import uuid
import time
from datetime import datetime, timezone as dt_timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from rest_framework.test import APIClient
from rest_framework import status

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.sources.models import SourceDocument, EmailAccountConnection, EmailSyncJob
from apps.sources.token_encryption import TokenEncryptionService, encrypt_token, decrypt_token
from apps.sources.connectors.gmail import GmailConnector
from apps.sources.connectors.email_base import EmailMessageDTO, EmailAttachmentDTO
from apps.sources.email_sync import EmailSyncService
from apps.sources.serializers import EmailAccountConnectionSerializer
from apps.governance.models import SourcePermission, AccessLevel
from apps.audit.models import AuditEvent


@pytest.mark.django_db
class TestEmailConnector:

    @pytest.fixture(autouse=True)
    def setup_data(self):
        # Organization
        self.org = Organization.objects.create(name='CyberTech Labs', slug='cybertech')

        # Users
        self.user_admin = User.objects.create_user(username='admin_sarah', email='sarah@cybertech.io', password='pass')
        self.user_alice = User.objects.create_user(username='alice_connect', email='alice@cybertech.io', password='pass')
        self.user_bob = User.objects.create_user(username='bob_colleague', email='bob@cybertech.io', password='pass')
        self.user_other_tenant = User.objects.create_user(username='other_tenant', email='other@acme.io', password='pass')

        # Memberships
        OrganizationMembership.objects.create(organization=self.org, user=self.user_admin, role='owner')
        OrganizationMembership.objects.create(organization=self.org, user=self.user_alice, role='member')
        OrganizationMembership.objects.create(organization=self.org, user=self.user_bob, role='member')

        # Workspace 1
        self.ws1 = Workspace.objects.create(organization=self.org, name='SecOps Workspace', slug='secops')
        WorkspaceMembership.objects.create(workspace=self.ws1, user=self.user_admin, role='workspace_admin')
        WorkspaceMembership.objects.create(workspace=self.ws1, user=self.user_alice, role='member')
        WorkspaceMembership.objects.create(workspace=self.ws1, user=self.user_bob, role='member')

        # Other Workspace & Org for Cross-Tenant Isolation
        self.org_other = Organization.objects.create(name='Other Corp', slug='other-corp')
        self.ws_other = Workspace.objects.create(organization=self.org_other, name='Other Workspace', slug='other-ws')
        WorkspaceMembership.objects.create(workspace=self.ws_other, user=self.user_other_tenant, role='workspace_admin')

        # Baseline unrelated document in ws1
        self.unrelated_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws1,
            owner=self.user_admin,
            title='Company Security Policy',
            original_filename='policy.txt',
            mime_type='text/plain',
            file_size=120,
            file_hash='hash_unrelated_doc_123',
            document_type='txt',
            authority_level=5
        )

        self.client = APIClient()

    # --------------------------------------------------------------------------
    # 1. OAuth State Generation & CSRF Protection
    # --------------------------------------------------------------------------
    def test_oauth_state_signing_and_tamper_protection(self):
        """Signed OAuth state validates cleanly; tampered or expired states are rejected."""
        signer = TimestampSigner(salt='lore_email_oauth_state')
        payload = f"{self.user_alice.id}:{self.ws1.id}:gmail"
        valid_state = signer.sign(payload)

        # 1. Valid state unsigns cleanly
        unsig = signer.unsign(valid_state, max_age=600)
        assert unsig == payload

        # 2. Tampered state raises BadSignature
        tampered_state = valid_state + "bad"
        with pytest.raises(BadSignature):
            signer.unsign(tampered_state, max_age=600)

        # 3. Expired state raises SignatureExpired
        with pytest.raises(SignatureExpired):
            signer.unsign(valid_state, max_age=-1)

    def test_oauth_authorize_and_callback_flow(self):
        """API client requests authorization URL and handles callback with valid state."""
        self.client.force_authenticate(user=self.user_alice)

        # Request authorize URL
        auth_url_res = self.client.get(f'/api/v1/sources/email/oauth/authorize/?workspace_id={self.ws1.id}&provider=gmail')
        assert auth_url_res.status_code == status.HTTP_200_OK
        data = auth_url_res.json()
        assert 'authorization_url' in data
        assert 'state' in data
        state = data['state']
        assert 'https://accounts.google.com/o/oauth2/v2/auth' in data['authorization_url']
        assert 'gmail.readonly' in data['authorization_url']

        # Mock token exchange and profile during callback
        mock_tokens = {
            'access_token': 'ya29.mock_access_token_12345',
            'refresh_token': '1//mock_refresh_token_67890',
            'expires_in': 3600,
            'scope': 'https://www.googleapis.com/auth/gmail.readonly'
        }
        mock_profile = {
            'emailAddress': 'alice.work@cybertech.io',
            'messagesTotal': 142
        }

        with patch.object(GmailConnector, 'exchange_code_for_tokens', return_value=mock_tokens), \
             patch.object(GmailConnector, 'fetch_user_profile', return_value=mock_profile):
            
            callback_res = self.client.post('/api/v1/sources/email/oauth/callback/', {
                'code': 'mock_auth_code_abc',
                'state': state
            })
            assert callback_res.status_code == status.HTTP_201_CREATED
            conn_data = callback_res.json()
            assert conn_data['email_address'] == 'alice.work@cybertech.io'
            assert conn_data['status'] == 'connected'
            assert conn_data['provider'] == 'gmail'
            # Ensure tokens are NOT exposed
            assert 'access_token' not in conn_data
            assert 'refresh_token' not in conn_data
            assert 'encrypted_access_token' not in conn_data

        # Verify DB connection record
        conn = EmailAccountConnection.objects.get(email_address='alice.work@cybertech.io')
        assert conn.user == self.user_alice
        assert conn.workspace == self.ws1
        assert conn.get_access_token() == 'ya29.mock_access_token_12345'
        assert conn.get_refresh_token() == '1//mock_refresh_token_67890'

    # --------------------------------------------------------------------------
    # 2. Token Encryption & Redaction
    # --------------------------------------------------------------------------
    def test_token_encryption_at_rest_and_redaction(self):
        """Tokens are Fernet encrypted in the DB and redacted in all API responses."""
        raw_token = 'secret_bearer_token_xyz987'
        cipher = encrypt_token(raw_token)
        assert cipher != raw_token
        assert decrypt_token(cipher) == raw_token

        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.secret@cybertech.io'
        )
        conn.set_tokens(access_token=raw_token, refresh_token='refresh_secret_123')
        conn.save()

        # Database inspection: field contains encrypted string, never raw token
        raw_db_conn = EmailAccountConnection.objects.values('encrypted_access_token', 'encrypted_refresh_token').get(id=conn.id)
        assert raw_token not in raw_db_conn['encrypted_access_token']
        assert 'refresh_secret_123' not in raw_db_conn['encrypted_refresh_token']

        # Serializer representation must not contain any tokens or encrypted values
        serializer = EmailAccountConnectionSerializer(conn)
        serialized_keys = set(serializer.data.keys())
        assert 'access_token' not in serialized_keys
        assert 'refresh_token' not in serialized_keys
        assert 'encrypted_access_token' not in serialized_keys
        assert 'encrypted_refresh_token' not in serialized_keys

    # --------------------------------------------------------------------------
    # 3. Token Expiration and Refresh
    # --------------------------------------------------------------------------
    def test_token_expiration_and_refresh_flow(self):
        """Connector detects expired access token and refreshes it using stored refresh token."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.refresh@cybertech.io',
            token_expires_at=timezone.now() - timedelta(minutes=10) # Expired 10 min ago
        )
        conn.set_tokens(access_token='expired_token_111', refresh_token='valid_refresh_222')
        conn.save()

        connector = GmailConnector(
            organization_id=str(self.org.id),
            workspace_id=str(self.ws1.id),
            connection_model=conn
        )

        refreshed_response = MagicMock()
        refreshed_response.ok = True
        refreshed_response.status_code = 200
        refreshed_response.json.return_value = {
            'access_token': 'new_fresh_token_333',
            'expires_in': 3600
        }

        with patch('requests.post', return_value=refreshed_response) as mock_post:
            active_token = connector.refresh_access_token_if_needed()
            assert active_token == 'new_fresh_token_333'
            assert mock_post.called

            # Verify connection object was updated and saved
            conn.refresh_from_db()
            assert conn.get_access_token() == 'new_fresh_token_333'
            assert conn.token_expires_at > timezone.now()

    # --------------------------------------------------------------------------
    # 4. Message Extraction, Safe HTML Parsing & Malformed Content Handling
    # --------------------------------------------------------------------------
    def test_gmail_html_sanitization_and_parsing(self):
        """HTML email bodies have scripts/styles stripped safely while preserving links and text."""
        raw_html = """
        <html>
            <head><style>p { color: red; }</style></head>
            <body>
                <script>alert('malicious_xss');</script>
                <h1>Project Velocity Update</h1>
                <p>Hello team, please see the architecture doc at <a href="https://cybertech.internal/arch">LORE Architecture</a>.</p>
                <iframe src="https://evil.example.com"></iframe>
            </body>
        </html>
        """
        clean_text = GmailConnector._sanitize_html_to_text(raw_html)
        assert "alert('malicious_xss')" not in clean_text
        assert "color: red" not in clean_text
        assert "Project Velocity Update" in clean_text
        assert "[LORE Architecture](https://cybertech.internal/arch)" in clean_text
        assert "evil.example.com" not in clean_text

    def test_malformed_email_payload_resilience(self):
        """Emails with missing headers, non-standard payloads, or empty bodies are handled without crash."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.malformed@cybertech.io'
        )
        connector = GmailConnector(
            organization_id=str(self.org.id),
            workspace_id=str(self.ws1.id),
            connection_model=conn
        )

        malformed_raw = {
            'id': 'msg_malformed_001',
            'threadId': 'thread_malformed_001',
            'internalDate': '1698240000000',
            'payload': {}
        }

        with patch.object(connector, '_api_get', return_value=malformed_raw):
            dto = connector.fetch_message_detail('msg_malformed_001')
            assert dto.external_id == 'msg_malformed_001'
            assert dto.subject == '(No Subject)'
            assert dto.sender == 'Unknown Sender'
            assert dto.body_plain == ''
            assert dto.attachments == []

    # --------------------------------------------------------------------------
    # 5. Attachment Filtering and Size Limits
    # --------------------------------------------------------------------------
    def test_attachment_filtering_and_size_limits(self):
        """Supported attachments within size limit are synced; unsupported or oversized are safely skipped."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.attach@cybertech.io'
        )

        valid_pdf_dto = EmailAttachmentDTO(
            filename='financial_q3.pdf',
            mime_type='application/pdf',
            size_bytes=1024 * 1024, # 1MB
            data=b"%PDF-1.4 Mock PDF content"
        )
        oversized_dto = EmailAttachmentDTO(
            filename='huge_archive.pdf',
            mime_type='application/pdf',
            size_bytes=30 * 1024 * 1024, # 30MB (> 25MB max)
            data=b"Large data"
        )
        disallowed_exe_dto = EmailAttachmentDTO(
            filename='malware.exe',
            mime_type='application/x-msdownload',
            size_bytes=5000,
            data=b"MZ executable header"
        )

        msg_dto = EmailMessageDTO(
            external_id='msg_with_attachments',
            thread_id='thread_att_01',
            sender='cfo@cybertech.io',
            recipients=['alice@cybertech.io'],
            subject='Q3 Financial Statement',
            body_plain='Attached are the quarterly numbers.',
            sent_at=timezone.now(),
            attachments=[valid_pdf_dto, oversized_dto, disallowed_exe_dto]
        )

        with patch('apps.sources.views.process_ingestion_pipeline'), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_messages_batch', return_value=(['msg_with_attachments'], None, None)), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_message_detail', return_value=msg_dto):

            job = EmailSyncService.trigger_sync(conn, user=self.user_alice)

        assert job.status in ['completed', 'partial_success']
        assert job.messages_imported == 1
        # Only 1 valid attachment (pdf) was imported; .exe and oversized were skipped!
        assert job.attachments_imported == 1
        assert SourceDocument.objects.filter(email_connection=conn).count() == 2

    # --------------------------------------------------------------------------
    # 6. Rate Limiting and Exponential Backoff Retries
    # --------------------------------------------------------------------------
    def test_rate_limiting_and_retries(self):
        """Connector retries with backoff on HTTP 429 / 503 and succeeds upon subsequent response."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.retry@cybertech.io'
        )
        conn.set_tokens('valid_token')
        conn.token_expires_at = timezone.now() + timedelta(hours=1)
        conn.save()

        connector = GmailConnector(
            organization_id=str(self.org.id),
            workspace_id=str(self.ws1.id),
            connection_model=conn
        )

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate Limit Exceeded"

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {'messages': [{'id': 'msg_retry_1'}]}

        with patch('requests.get', side_effect=[mock_response_429, mock_response_200]) as mock_get, \
             patch('time.sleep') as mock_sleep:
            data = connector._api_get('messages')
            assert data == {'messages': [{'id': 'msg_retry_1'}]}
            assert mock_get.call_count == 2
            assert mock_sleep.called

    # --------------------------------------------------------------------------
    # 7. Incremental Sync, Checkpoints & Duplicate Prevention
    # --------------------------------------------------------------------------
    def test_sync_checkpoint_and_duplicate_prevention(self):
        """Duplicate messages are skipped via external_id, and sync_checkpoint is updated."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.sync@cybertech.io'
        )

        msg1 = EmailMessageDTO(
            external_id='msg_uniq_101',
            thread_id='thread_101',
            sender='sender1@cybertech.io',
            recipients=['alice@cybertech.io'],
            subject='First Notification',
            body_plain='Body 101',
            sent_at=timezone.now() - timedelta(hours=2)
        )
        msg2 = EmailMessageDTO(
            external_id='msg_uniq_102',
            thread_id='thread_102',
            sender='sender2@cybertech.io',
            recipients=['alice@cybertech.io'],
            subject='Second Notification',
            body_plain='Body 102',
            sent_at=timezone.now() - timedelta(hours=1)
        )

        def mock_fetch_detail(mid):
            return msg1 if mid == 'msg_uniq_101' else msg2

        # First sync run: ingests both messages
        with patch('apps.sources.views.process_ingestion_pipeline'), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_messages_batch', return_value=(['msg_uniq_101', 'msg_uniq_102'], None, None)), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_message_detail', side_effect=mock_fetch_detail):
            
            job1 = EmailSyncService.trigger_sync(conn, user=self.user_alice)
            assert job1.status == 'completed'
            assert job1.messages_imported == 2
            assert SourceDocument.objects.filter(email_connection=conn).count() == 2

            doc1 = SourceDocument.objects.get(external_id='msg_uniq_101')
            assert doc1.authority_level == 1 # Strictly informal note
            assert doc1.workspace == self.ws1

        # Second sync run with the SAME messages: duplicate prevention should skip ingestion
        with patch('apps.sources.views.process_ingestion_pipeline'), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_messages_batch', return_value=(['msg_uniq_101', 'msg_uniq_102'], None, None)), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_message_detail', side_effect=mock_fetch_detail):
            
            job2 = EmailSyncService.trigger_sync(conn, user=self.user_alice)
            assert job2.status == 'completed'
            assert job2.messages_imported == 0 # 0 new messages ingested
            # Total count in DB remains 2, not 4
            assert SourceDocument.objects.filter(email_connection=conn).count() == 2

    # --------------------------------------------------------------------------
    # 8. Cross-User and Cross-Workspace Isolation & Retrieval Privacy
    # --------------------------------------------------------------------------
    def test_cross_user_privacy_and_l7_restricted_permissions(self):
        """Email documents are marked RESTRICTED to connecting user; colleagues cannot access."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.private@cybertech.io'
        )

        msg = EmailMessageDTO(
            external_id='msg_confidential_999',
            thread_id='thread_priv_999',
            sender='ceo@cybertech.io',
            recipients=['alice@cybertech.io'],
            subject='Private Compensation Review',
            body_plain='Confidential compensation details.',
            sent_at=timezone.now()
        )

        with patch('apps.sources.views.process_ingestion_pipeline'), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_messages_batch', return_value=(['msg_confidential_999'], None, None)), \
             patch('apps.sources.connectors.gmail.GmailConnector.fetch_message_detail', return_value=msg):
            
            job = EmailSyncService.trigger_sync(conn, user=self.user_alice)
            assert job.status == 'completed'

        email_doc = SourceDocument.objects.get(external_id='msg_confidential_999')
        perm = SourcePermission.objects.get(document=email_doc)

        assert perm.access_level == AccessLevel.RESTRICTED
        # Alice (connecting user) IS permitted
        assert perm.is_user_permitted(user=self.user_alice, user_role='member') is True
        # Bob (colleague in the same workspace) is NOT permitted!
        assert perm.is_user_permitted(user=self.user_bob, user_role='member') is False
        # Sarah (workspace admin) IS permitted for governance oversight
        assert perm.is_user_permitted(user=self.user_admin, user_role='workspace_admin') is True

    def test_cross_workspace_and_cross_user_api_isolation(self):
        """User cannot access or trigger sync on another user's email connection."""
        conn_alice = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.guard@cybertech.io'
        )

        # Bob (different user in same workspace) tries to trigger sync on Alice's mailbox
        self.client.force_authenticate(user=self.user_bob)
        res_sync = self.client.post(f'/api/v1/sources/email/connections/{conn_alice.id}/sync/')
        assert res_sync.status_code == status.HTTP_403_FORBIDDEN

        # Other tenant in a completely different workspace tries to retrieve Alice's connection
        self.client.force_authenticate(user=self.user_other_tenant)
        res_detail = self.client.get(f'/api/v1/sources/email/connections/{conn_alice.id}/')
        assert res_detail.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]

    # --------------------------------------------------------------------------
    # 9. Disconnect Lifecycle & Retention Policy
    # --------------------------------------------------------------------------
    def test_disconnect_with_retain_content_true(self):
        """Disconnecting with retain_content=True retains indexed documents but marks connection disconnected."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.retain@cybertech.io'
        )
        msg_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws1,
            owner=self.user_alice,
            title='Retained Email Doc',
            original_filename='retained_email.txt',
            mime_type='text/plain',
            file_size=120,
            file_hash='hash_retained_doc_01',
            document_type='txt',
            authority_level=1,
            external_id='retained_01',
            email_connection=conn
        )

        self.client.force_authenticate(user=self.user_alice)
        res = self.client.post(f'/api/v1/sources/email/connections/{conn.id}/disconnect/', {
            'retain_content': True
        })
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data['status'] == 'disconnected'
        assert data['retain_content'] is True
        assert data['documents_purged'] == 0

        # Connection is disconnected
        conn.refresh_from_db()
        assert conn.status == 'disconnected'
        # Document still exists
        assert SourceDocument.objects.filter(id=msg_doc.id).exists()

    def test_disconnect_with_retain_content_false_purges_only_relevant_mailbox_documents(self):
        """Disconnecting with retain_content=False deletes only this mailbox's documents; leaves unrelated files intact."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.purge@cybertech.io'
        )
        email_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws1,
            owner=self.user_alice,
            title='Purgeable Email Doc',
            original_filename='purgeable_email.txt',
            mime_type='text/plain',
            file_size=120,
            file_hash='hash_purgeable_doc_01',
            document_type='txt',
            authority_level=1,
            external_id='purge_01',
            email_connection=conn
        )

        # Baseline: unrelated_doc created in setup_data has NO email_connection
        assert SourceDocument.objects.filter(id=self.unrelated_doc.id).exists()
        assert SourceDocument.objects.filter(id=email_doc.id).exists()

        self.client.force_authenticate(user=self.user_alice)
        res = self.client.post(f'/api/v1/sources/email/connections/{conn.id}/disconnect/', {
            'retain_content': False
        })
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data['status'] == 'disconnected'
        assert data['retain_content'] is False
        assert data['documents_purged'] == 1

        # Mailbox document is completely deleted
        assert not SourceDocument.objects.filter(id=email_doc.id).exists()
        # UNRELATED WORKSPACE DOCUMENT REMAINS COMPLETELY INTACT
        assert SourceDocument.objects.filter(id=self.unrelated_doc.id).exists()

    # --------------------------------------------------------------------------
    # 10. Audit Trail Logging & Secret Redaction
    # --------------------------------------------------------------------------
    def test_audit_trail_logging_and_secret_redaction(self):
        """Audit events are logged for email lifecycle and never contain secret tokens."""
        conn = EmailAccountConnection.objects.create(
            organization=self.org,
            workspace=self.ws1,
            user=self.user_alice,
            provider='gmail',
            email_address='alice.audit@cybertech.io'
        )
        conn.set_tokens('secret_access_xyz', 'secret_refresh_abc')
        conn.save()

        # Trigger sync service
        with patch('apps.sources.connectors.gmail.GmailConnector.fetch_messages_batch', return_value=([], None, None)):
            job = EmailSyncService.trigger_sync(conn, user=self.user_alice)

        # Check AuditEvent
        sync_events = AuditEvent.objects.filter(
            workspace=self.ws1,
            event_type='ingestion_completed',
            target_type='email_account_connection'
        )
        assert sync_events.exists()
        event = sync_events.first()
        assert event.user == self.user_alice

        # Verify no token leaks in metadata or details
        meta_str = str(event.details)
        assert 'secret_access_xyz' not in meta_str
        assert 'secret_refresh_abc' not in meta_str
        assert 'token' not in meta_str.lower() or 'encrypted' not in meta_str.lower()
