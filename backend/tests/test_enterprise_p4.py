import os
import tempfile
import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity.models import Organization, OrganizationMembership
from apps.identity.scim import SCIMService
from apps.identity.residency import DataResidencyService, DataResidencyViolation
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument
from apps.sources.connectors.local_folder import LocalFolderConnector
from apps.audit.models import AuditEvent
from apps.retrieval.cache import TenantSafeCacheService

@pytest.mark.django_db
class TestEnterpriseP4Integrations:

    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.org = Organization.objects.create(name='P4 Enterprise Org', slug='p4-ent-org')
        self.admin = User.objects.create_user(username='p4_admin', email='p4admin@lore.com', password='pass')
        OrganizationMembership.objects.create(organization=self.org, user=self.admin, role='owner')

        self.ws = Workspace.objects.create(organization=self.org, name='P4 Workspace', slug='p4-ws')
        WorkspaceMembership.objects.create(workspace=self.ws, user=self.admin, role='workspace_admin')

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_scim_create_user(self):
        """
        Verify SCIM 2.0 user provisioning creates the user and binds to organization.
        """
        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "jill.valentine@acme.com",
            "name": {
                "givenName": "Jill",
                "familyName": "Valentine"
            },
            "emails": [{"value": "jill.valentine@acme.com", "primary": True}],
            "active": True
        }

        user_scim = SCIMService.create_user(payload, org_id=str(self.org.id))
        assert user_scim["userName"] == "jill.valentine@acme.com"
        assert user_scim["active"] is True

        user_db = User.objects.get(username="jill.valentine@acme.com")
        assert user_db.email == "jill.valentine@acme.com"
        assert OrganizationMembership.objects.filter(organization=self.org, user=user_db).exists()

    def test_scim_update_and_deactivate_user(self):
        """
        Verify SCIM 2.0 user updating and soft deactivation.
        """
        user = User.objects.create_user(username='chris.redfield', email='chris@bsaa.org')
        
        # Update user
        updated = SCIMService.update_user(user.id, {
            "name": {"givenName": "Captain Chris", "familyName": "Redfield"},
            "emails": [{"value": "captain.chris@bsaa.org"}]
        })
        user.refresh_from_db()
        assert user.first_name == "Captain Chris"
        assert user.email == "captain.chris@bsaa.org"

        # Deactivate user
        SCIMService.deactivate_user(user.id)
        user.refresh_from_db()
        assert user.is_active is False

    def test_scim_api_endpoints(self):
        """
        Verify HTTP endpoints for SCIM 2.0 /Users and /Groups.
        """
        # GET /Users
        res = self.client.get('/api/v1/identity/scim/v2/Users')
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert 'totalResults' in data
        assert data['totalResults'] >= 1

        # GET /Groups
        res_groups = self.client.get('/api/v1/identity/scim/v2/Groups')
        assert res_groups.status_code == status.HTTP_200_OK
        groups_data = res_groups.json()
        assert 'totalResults' in groups_data
        assert groups_data['totalResults'] >= 1

    def test_scim_group_membership_sync(self):
        """
        Verify SCIM group synchronization updates workspace role memberships.
        """
        new_user = User.objects.create_user(username='leon.kennedy', email='leon@dsso.gov')
        res = SCIMService.sync_group_members(
            workspace_id=str(self.ws.id),
            member_user_ids=[new_user.id],
            role='contributor'
        )

        assert res['id'] == str(self.ws.id)
        membership = WorkspaceMembership.objects.filter(workspace=self.ws, user=new_user).first()
        assert membership is not None
        assert membership.role == 'contributor'

    def test_data_residency_sovereign_enforcement(self):
        """
        Verify DataResidencyService strictly blocks cross-boundary and air-gapped egress.
        """
        # 1. Compliant same-region transfers pass
        assert DataResidencyService.check_residency_compliance('us', 'us') is True
        assert DataResidencyService.check_residency_compliance('eu', 'eu') is True

        # 2. Air-gapped onprem strictly forbids cloud transfer
        with pytest.raises(DataResidencyViolation) as exc_info:
            DataResidencyService.check_residency_compliance('local_onprem', 'us')
        assert "Air-gapped on-premise data cannot egress" in str(exc_info.value)

        # 3. EU GDPR boundary forbids transfer to US
        with pytest.raises(DataResidencyViolation) as exc_eu:
            DataResidencyService.check_residency_compliance('eu', 'us')
        assert "EU GDPR sovereign data cannot be processed" in str(exc_eu.value)

    def test_local_folder_connector_execution(self):
        """
        Verify LocalFolderConnector scans directories, discovers files, and yields SyncEvents.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_a = os.path.join(tmp_dir, 'policy_a.txt')
            file_b = os.path.join(tmp_dir, 'spec_b.md')
            with open(file_a, 'wb') as f:
                f.write(b"Company security policy text.")
            with open(file_b, 'wb') as f:
                f.write(b"# Product Specification\nDetails of module B.")

            connector = LocalFolderConnector(
                organization_id=str(self.org.id),
                workspace_id=str(self.ws.id),
                config={'folder_path': tmp_dir, 'rate_limit_delay_seconds': 0.0}
            )

            assert connector.test_connection() is True
            sync_res = connector.sync(full_sync=True)

            assert sync_res.success is True
            assert sync_res.events_detected == 2
            assert sync_res.documents_created == 2
            assert sync_res.next_checkpoint is not None
            assert sync_res.next_checkpoint.cursor is not None

    def test_review_queue_human_workflow(self):
        """
        Verify Compliance Review Queue approval and rejection endpoints,
        with provenance audit logging and workspace cache invalidation.
        """
        # Create unverified document needing review
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            owner=self.admin,
            title='Suspicious Claim Document',
            original_filename='suspicious.md',
            mime_type='text/markdown',
            file_size=200,
            file_hash='hash-suspicious',
            file_obj=SimpleUploadedFile('suspicious.md', b"Unverified claims"),
            document_type='txt',
            authority_level=2,
            ocr_confidence=0.55,
            status='needs_review'
        )

        # Pre-seed cache
        TenantSafeCacheService.set(
            organization_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='suspicious claim',
            envelope={'state': 'supported', 'directive': 'proceed_and_cite'}
        )
        assert TenantSafeCacheService.get(
            organization_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='suspicious claim'
        ) is not None

        # 1. Human Approve -> marks 'ready', purges cache, creates 'item_promoted' audit
        res_approve = self.client.post(f'/api/v1/governance/review/{doc.id}/approve/')
        assert res_approve.status_code == status.HTTP_200_OK
        doc.refresh_from_db()
        assert doc.status == 'ready'

        # Cache must be invalidated
        assert TenantSafeCacheService.get(
            organization_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='suspicious claim'
        ) is None

        # Audit event recorded
        assert AuditEvent.objects.filter(
            event_type='item_promoted',
            target_id=str(doc.id)
        ).exists()

        # 2. Human Reject -> test on a separate unverified document needing review
        doc_reject = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            owner=self.admin,
            title='Another Suspicious Document',
            original_filename='suspicious_2.md',
            mime_type='text/markdown',
            file_size=250,
            file_hash='hash-suspicious-2',
            file_obj=SimpleUploadedFile('suspicious_2.md', b"Bad claims"),
            document_type='txt',
            authority_level=1,
            ocr_confidence=0.40,
            status='needs_review'
        )
        res_reject = self.client.post(f'/api/v1/governance/review/{doc_reject.id}/reject/')
        assert res_reject.status_code == status.HTTP_200_OK
        doc_reject.refresh_from_db()
        assert doc_reject.status == 'quarantined'

        assert AuditEvent.objects.filter(
            event_type='item_quarantined',
            target_id=str(doc_reject.id)
        ).exists()
