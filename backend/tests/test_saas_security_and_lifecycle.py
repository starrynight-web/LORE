import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from apps.identity.models import Organization, OrganizationMembership, OrganizationInvitation
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.sources.models import SourceDocument, DocumentVersion
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline
from apps.subscriptions.models import Plan, Subscription, UsageRecord
from apps.subscriptions.services import QuotaEnforcementService
from apps.retrieval.embeddings import SentenceTransformerEmbeddingAdapter, get_embedding_adapter
from apps.retrieval.services import HybridRetrievalService
from apps.decisions.engine import AnswerStateMachine

@pytest.mark.django_db
class TestSaaSSecurityAndLifecycle:

    @pytest.fixture(autouse=True)
    def setup_data(self):
        # 1. Plans
        self.plan_starter = Plan.objects.create(
            name='Starter Tier', slug='starter', price_monthly=49.00,
            max_storage_mb=500, max_documents=5, max_monthly_queries=100,
            max_workspaces=2, max_members=5, allow_custom_models=False
        )
        self.plan_enterprise = Plan.objects.create(
            name='Enterprise Scale', slug='enterprise-scale', price_monthly=299.00,
            max_storage_mb=10000, max_documents=1000, max_monthly_queries=20000,
            max_workspaces=25, max_members=50, allow_custom_models=True
        )

        # 2. Tenant 1: Northstar Digital
        self.org1 = Organization.objects.create(name='Northstar Digital', slug='northstar-digital')
        self.user1_admin = User.objects.create_user(username='sarah_admin', email='sarah@northstar.demo', password='pass')
        self.user1_viewer = User.objects.create_user(username='elena_viewer', email='elena@northstar.demo', password='pass')

        OrganizationMembership.objects.create(organization=self.org1, user=self.user1_admin, role='owner')
        OrganizationMembership.objects.create(organization=self.org1, user=self.user1_viewer, role='member')

        self.sub1 = Subscription.objects.create(organization=self.org1, plan=self.plan_enterprise, status='active')

        self.ws1 = Workspace.objects.create(organization=self.org1, name='SecOps Workspace', slug='secops')
        WorkspaceMembership.objects.create(workspace=self.ws1, user=self.user1_admin, role='workspace_admin')
        WorkspaceMembership.objects.create(workspace=self.ws1, user=self.user1_viewer, role='viewer')

        # 3. Tenant 2: Acme Aerospace
        self.org2 = Organization.objects.create(name='Acme Aerospace', slug='acme-aero')
        self.user2_admin = User.objects.create_user(username='frank_acme', email='frank@acme.demo', password='pass')
        OrganizationMembership.objects.create(organization=self.org2, user=self.user2_admin, role='owner')
        self.sub2 = Subscription.objects.create(organization=self.org2, plan=self.plan_starter, status='active')
        self.ws2 = Workspace.objects.create(organization=self.org2, name='Avionics Workspace', slug='avionics')
        WorkspaceMembership.objects.create(workspace=self.ws2, user=self.user2_admin, role='workspace_admin')

        # Seed Document for Tenant 1
        t1_content = (
            "# Cloud Security Directive POL-01\n"
            "All cloud storage must enforce AES-256 at rest. Third party vendors require formal approval."
        ).encode('utf-8')
        self.doc1 = SourceDocument.objects.create(
            organization=self.org1, workspace=self.ws1, owner=self.user1_admin,
            title='POL-01: Storage Encryption', original_filename='pol01.md',
            mime_type='text/markdown', file_size=len(t1_content), file_hash='hash-pol-01',
            file_obj=SimpleUploadedFile('pol01.md', t1_content), document_type='txt',
            authority_level=7, status='queued'
        )
        job1 = IngestionJob.objects.create(document=self.doc1, organization=self.org1, workspace=self.ws1)
        process_ingestion_pipeline(str(job1.id))
        self.doc1.refresh_from_db()

        # Seed Document for Tenant 2
        t2_content = (
            "# ACME Secret Avionics Spec\n"
            "Top secret flight guidance radar algorithms strictly proprietary to Acme Aerospace."
        ).encode('utf-8')
        self.doc2 = SourceDocument.objects.create(
            organization=self.org2, workspace=self.ws2, owner=self.user2_admin,
            title='ACME-RADAR-SPEC', original_filename='radar.md',
            mime_type='text/markdown', file_size=len(t2_content), file_hash='hash-acme-radar',
            file_obj=SimpleUploadedFile('radar.md', t2_content), document_type='txt',
            authority_level=7, status='queued'
        )
        job2 = IngestionJob.objects.create(document=self.doc2, organization=self.org2, workspace=self.ws2)
        process_ingestion_pipeline(str(job2.id))
        self.doc2.refresh_from_db()

    def test_tenant_isolation_workspace_and_documents(self):
        """Proves Tenant 1 cannot access Tenant 2 workspace or documents via API."""
        client = APIClient()
        client.force_authenticate(user=self.user1_admin)

        # 1. Attempt to list documents in Tenant 2's workspace
        res = client.get(f'/api/v1/sources/documents/?workspace_id={self.ws2.id}')
        assert res.status_code == status.HTTP_200_OK
        # Must return empty results because user1 is not a member of ws2
        results = res.data.get('results', res.data)
        assert len(results) == 0
        assert res.data.get('count', 0) == 0

        # 2. Attempt direct document detail fetch of Tenant 2 document
        res_doc = client.get(f'/api/v1/sources/documents/{self.doc2.id}/')
        assert res_doc.status_code == status.HTTP_404_NOT_FOUND

        # 3. Attempt direct download of Tenant 2 document
        res_dl = client.get(f'/api/v1/sources/documents/{self.doc2.id}/download/')
        assert res_dl.status_code == status.HTTP_404_NOT_FOUND

    def test_tenant_isolation_vector_retrieval(self):
        """Proves cross-tenant leakage is impossible during hybrid vector retrieval."""
        service = HybridRetrievalService()

        # Query from Tenant 1 searching for Tenant 2 terms ("radar", "flight guidance")
        hits_t1 = service.search(
            query="flight guidance radar algorithms",
            workspace_id=str(self.ws1.id),
            organization_id=str(self.org1.id),
            limit=10
        )

        for h in hits_t1:
            assert h['document_title'] != 'ACME-RADAR-SPEC'
            assert str(h['document_id']) != str(self.doc2.id)

    def test_immutable_document_versioning(self):
        """Proves document versions are created immutably and linked to chunks & citations."""
        assert self.doc1.versions.count() == 1
        ver1 = self.doc1.versions.first()
        assert ver1.version_number == 1

        chunks = self.doc1.chunks.all()
        assert chunks.count() > 0
        for chk in chunks:
            assert chk.document_version == ver1

        # Query decision citations
        envelope = AnswerStateMachine.evaluate(
            query="storage encryption",
            retrieved_chunks=[{
                'chunk_id': str(chunks[0].id),
                'document_id': str(self.doc1.id),
                'document_title': self.doc1.title,
                'document_version': ver1.version_number,
                'page_number': 1,
                'heading_path': 'General',
                'text': chunks[0].text,
                'authority_level': 7,
                'score': 0.95
            }],
            workspace_id=str(self.ws1.id)
        )
        assert len(envelope['citations']) > 0
        assert envelope['citations'][0]['document_version'] == 1
        assert envelope['citations'][0]['document_id'] == str(self.doc1.id)

    def test_sentence_transformer_embedding_generation(self):
        """Proves local SentenceTransformer produces valid 384-dimensional dense vectors."""
        adapter = get_embedding_adapter()
        vec = adapter.embed_text("Governed RAG with anti-hallucination controls.")
        assert len(vec) == 384
        # Verify L2 normalized
        magnitude = sum(x * x for x in vec)
        assert pytest.approx(magnitude, 0.05) == 1.0

    def test_quota_enforcement_upload_cap(self):
        """Proves upload quota rejects documents when plan limit is reached."""
        client = APIClient()
        client.force_authenticate(user=self.user2_admin)

        # Plan Starter has max_documents=5
        # Set usage to 5
        rec = QuotaEnforcementService.get_or_create_usage_record(self.org2, self.ws2)
        rec.documents_count = 5
        rec.save()

        dummy_file = SimpleUploadedFile("over_limit.txt", b"Exceeding quota document content.")
        res = client.post('/api/v1/sources/documents/', {
            'workspace': str(self.ws2.id),
            'file': dummy_file
        }, format='multipart')

        assert res.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert res.data.get('quota_exceeded') is True

    def test_organization_invitation_lifecycle(self):
        """Proves invitations can be created by admin, copied, and accepted by a new user."""
        client = APIClient()
        client.force_authenticate(user=self.user1_admin)

        # 1. Create invitation
        res_invite = client.post(f'/api/v1/identity/organizations/{self.org1.id}/invitations/', {
            'email': 'newhire@northstar.demo',
            'role': 'admin'
        })
        assert res_invite.status_code == status.HTTP_201_CREATED
        token = res_invite.data['token']
        assert token is not None

        # 2. New user accepts invitation
        new_user = User.objects.create_user(username='newhire', email='newhire@northstar.demo', password='pass')
        client.force_authenticate(user=new_user)

        res_accept = client.post('/api/v1/identity/invitations/accept/', {'token': token})
        assert res_accept.status_code == status.HTTP_200_OK

        # Verify new user is now an organization member with 'admin' role
        membership = OrganizationMembership.objects.filter(organization=self.org1, user=new_user).first()
        assert membership is not None
        assert membership.role == 'admin'
