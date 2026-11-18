import pytest
from apps.identity.models import Organization, OrganizationMembership, User
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument
from apps.knowledge.models import CanonicalEntity, DocumentChunk
from apps.ingestion.models import IngestionJob
from rest_framework.test import APIClient

@pytest.mark.django_db
class TestWorkspaceCreationAndPurge:
    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='admin_test', email='admintest@example.com', password='password123')
        self.org = Organization.objects.create(name='Acme Corp', slug='acme-corp')
        self.org_mem = OrganizationMembership.objects.create(organization=self.org, user=self.user, role='admin')
        self.client.force_authenticate(user=self.user)

    def test_workspace_creation_without_slug_auto_populates(self):
        resp = self.client.post('/api/v1/workspaces/workspaces/', {
            'organization': str(self.org.id),
            'name': 'Legal',
            'description': 'Legal Workspace'
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data['slug'] == 'legal'
        assert data['name'] == 'Legal'
        assert WorkspaceMembership.objects.filter(workspace_id=data['id'], user=self.user, role='workspace_admin').exists()

    def test_workspace_creation_duplicate_slug_deduplication(self):
        r1 = self.client.post('/api/v1/workspaces/workspaces/', {
            'organization': str(self.org.id),
            'name': 'Research',
        })
        assert r1.status_code == 201
        assert r1.json()['slug'] == 'research'

        r2 = self.client.post('/api/v1/workspaces/workspaces/', {
            'organization': str(self.org.id),
            'name': 'Research',
        })
        assert r2.status_code == 201
        assert r2.json()['slug'] == 'research-1'

    def test_workspace_purge_database_deletes_only_target_workspace_data(self):
        # Create target workspace
        ws1 = Workspace.objects.create(organization=self.org, name='Target WS', slug='target-ws')
        WorkspaceMembership.objects.create(workspace=ws1, user=self.user, role='workspace_admin')

        # Create another workspace
        ws2 = Workspace.objects.create(organization=self.org, name='Other WS', slug='other-ws')
        WorkspaceMembership.objects.create(workspace=ws2, user=self.user, role='workspace_admin')

        # Add data to ws1
        doc1 = SourceDocument.objects.create(
            organization=self.org, workspace=ws1, title='Target Doc',
            original_filename='target.pdf', mime_type='application/pdf',
            file_size=1024, file_hash='hash1', owner=self.user, status='ready'
        )
        DocumentChunk.objects.create(
            organization=self.org, workspace=ws1, document=doc1,
            chunk_index=0, text='Target chunk', token_count=2
        )
        CanonicalEntity.objects.create(
            organization=self.org, workspace=ws1, name='Target Entity', entity_type='concept'
        )
        IngestionJob.objects.create(
            organization=self.org, workspace=ws1, document=doc1, status='completed'
        )

        # Add data to ws2
        doc2 = SourceDocument.objects.create(
            organization=self.org, workspace=ws2, title='Preserved Doc',
            original_filename='preserved.pdf', mime_type='application/pdf',
            file_size=2048, file_hash='hash2', owner=self.user, status='ready'
        )
        DocumentChunk.objects.create(
            organization=self.org, workspace=ws2, document=doc2,
            chunk_index=0, text='Preserved chunk', token_count=2
        )

        # Purge ws1
        purge_resp = self.client.post(f'/api/v1/workspaces/workspaces/{ws1.id}/purge-data/')
        assert purge_resp.status_code == 200
        pdata = purge_resp.json()
        assert pdata['status'] == 'SUCCESS'
        assert pdata['deleted_documents_count'] == 1
        assert pdata['deleted_entities_count'] == 1

        # Verify ws1 is empty
        assert SourceDocument.objects.filter(workspace=ws1).count() == 0
        assert DocumentChunk.objects.filter(workspace=ws1).count() == 0
        assert CanonicalEntity.objects.filter(workspace=ws1).count() == 0
        assert IngestionJob.objects.filter(workspace=ws1).count() == 0
        # Verify ws1 workspace entity itself still exists
        assert Workspace.objects.filter(id=ws1.id).exists()

        # Verify ws2 was untouched
        assert SourceDocument.objects.filter(workspace=ws2).count() == 1
        assert DocumentChunk.objects.filter(workspace=ws2).count() == 1

