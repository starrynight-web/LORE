import uuid
import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument, DocumentVersion
from apps.governance.models import SourcePermission, AccessLevel
from apps.knowledge.models import DocumentChunk
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.cache import TenantSafeCacheService
from apps.sources.reconciliation import StoreReconciliationService
from apps.sources.connectors.base import BaseConnector, SyncCheckpoint, SyncEvent, SyncResult
from apps.audit.models import AuditEvent

@pytest.mark.django_db
class TestEnterpriseLifecycleP2:

    @pytest.fixture(autouse=True)
    def setup_data(self):
        # 1. Organization & Users
        self.org = Organization.objects.create(name='P2 Lifecycle Org', slug='p2-org')
        self.admin = User.objects.create_user(username='p2_admin', email='p2admin@org.com', password='pass')
        self.viewer = User.objects.create_user(username='p2_viewer', email='p2viewer@org.com', password='pass')
        
        OrganizationMembership.objects.create(organization=self.org, user=self.admin, role='owner')
        OrganizationMembership.objects.create(organization=self.org, user=self.viewer, role='member')

        # 2. Workspace
        self.ws = Workspace.objects.create(organization=self.org, name='P2 Workspace', slug='p2-ws')
        WorkspaceMembership.objects.create(workspace=self.ws, user=self.admin, role='workspace_admin')
        WorkspaceMembership.objects.create(workspace=self.ws, user=self.viewer, role='viewer')

        # 3. Document 1
        content_1 = (
            "# Data Retention Policy\n"
            "Customer data records must be retained for 7 years per regulatory guidelines.\n\n"
            "## Storage Media\n"
            "All long-term archives must be stored in encrypted cold storage tiers."
        ).encode('utf-8')
        
        self.doc1 = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            owner=self.admin,
            title='Data Retention Policy',
            original_filename='retention.md',
            mime_type='text/markdown',
            file_size=len(content_1),
            file_hash='hash-retention-v1',
            file_obj=SimpleUploadedFile('retention.md', content_1),
            document_type='txt',
            authority_level=6,
            status='queued'
        )

        self.vstore = QdrantVectorStore()

    def test_idempotent_ingestion_reprocessing(self):
        """
        Verify that running ingestion multiple times for the same document is strictly idempotent.
        Postgres chunks and Qdrant points must not duplicate.
        """
        job1 = IngestionJob.objects.create(
            document=self.doc1, organization=self.org, workspace=self.ws
        )
        process_ingestion_pipeline(str(job1.id))
        self.doc1.refresh_from_db()
        assert self.doc1.status == 'ready'

        initial_pg_chunks = DocumentChunk.objects.filter(document=self.doc1).count()
        assert initial_pg_chunks > 0

        initial_qdrant_vectors = self.vstore.count_document_chunks("lore_chunks", str(self.doc1.id))
        assert initial_qdrant_vectors == initial_pg_chunks

        # Re-run pipeline with a second job (simulating retry or re-indexing)
        job2 = IngestionJob.objects.create(
            document=self.doc1, organization=self.org, workspace=self.ws
        )
        process_ingestion_pipeline(str(job2.id))
        self.doc1.refresh_from_db()

        second_pg_chunks = DocumentChunk.objects.filter(document=self.doc1).count()
        second_qdrant_vectors = self.vstore.count_document_chunks("lore_chunks", str(self.doc1.id))

        assert second_pg_chunks == initial_pg_chunks
        assert second_qdrant_vectors == initial_qdrant_vectors

    def test_stale_worker_protection(self):
        """
        Verify that an older background ingestion job cannot overwrite a newer document version.
        """
        from unittest.mock import patch
        from apps.ingestion.pipeline.extractors import UnifiedDocumentExtractor

        content_v1 = b"# Version 1 Content"
        stale_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            owner=self.admin,
            title='Stale Worker Test Doc',
            original_filename='stale.md',
            mime_type='text/markdown',
            file_size=len(content_v1),
            file_hash='hash-stale-v1',
            file_obj=SimpleUploadedFile('stale.md', content_v1),
            document_type='txt',
            authority_level=5,
            current_version_number=1,
            status='queued'
        )

        job_v1 = IngestionJob.objects.create(
            document=stale_doc, organization=self.org, workspace=self.ws
        )

        orig_extract = UnifiedDocumentExtractor.extract_document

        def simulate_concurrent_upload_during_extraction(extractor_self, *args, **kwargs):
            # Concurrent process increments document version to 2 during extraction
            SourceDocument.objects.filter(id=stale_doc.id).update(current_version_number=2)
            return orig_extract(extractor_self, *args, **kwargs)

        with patch.object(UnifiedDocumentExtractor, 'extract_document', side_effect=simulate_concurrent_upload_during_extraction, autospec=True):
            process_ingestion_pipeline(str(job_v1.id))

        job_v1.refresh_from_db()
        stale_doc.refresh_from_db()

        assert job_v1.status == 'failed'
        assert job_v1.error_category == 'STALE_VERSION_OVERWRITE_PREVENTED'
        assert stale_doc.current_version_number == 2

        audit_event = AuditEvent.objects.filter(
            event_type='stale_worker_aborted',
            target_id=str(stale_doc.id)
        ).first()
        assert audit_event is not None
        assert audit_event.details['job_version'] == 1
        assert audit_event.details['current_version'] == 2

    def test_cascading_deletion_signal(self):
        """
        Verify that deleting a SourceDocument automatically triggers post_delete signals
        to delete vector embeddings in Qdrant and invalidate workspace cache.
        """
        job = IngestionJob.objects.create(
            document=self.doc1, organization=self.org, workspace=self.ws
        )
        process_ingestion_pipeline(str(job.id))
        
        doc_id_str = str(self.doc1.id)
        assert self.vstore.count_document_chunks("lore_chunks", doc_id_str) > 0

        # Prime the cache for this workspace
        TenantSafeCacheService.set(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='retention policy',
            value={'data': 'cached_retention'}
        )
        assert TenantSafeCacheService.get(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='retention policy'
        ) is not None

        # Delete document
        self.doc1.delete()

        # Qdrant chunks must be purged
        assert self.vstore.count_document_chunks("lore_chunks", doc_id_str) == 0

        # Workspace query cache must be invalidated
        assert TenantSafeCacheService.get(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='retention policy'
        ) is None

        # Audit event recorded
        assert AuditEvent.objects.filter(
            event_type='item_deleted',
            target_id=doc_id_str
        ).exists()

    def test_permission_change_cache_invalidation(self):
        """
        Verify that granting or revoking permissions purges the workspace query cache,
        preventing unauthorized answers from being served from cache.
        """
        TenantSafeCacheService.set(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='viewer',
            query='confidential audit',
            value={'data': 'sensitive_cached_answer'}
        )
        assert TenantSafeCacheService.get(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='viewer',
            query='confidential audit'
        ) is not None

        # Change permission
        perm, _ = SourcePermission.objects.get_or_create(
            document=self.doc1,
            defaults={'access_level': AccessLevel.RESTRICTED, 'allowed_roles': ['admin']}
        )
        perm.access_level = AccessLevel.CONFIDENTIAL
        perm.save()

        # Cache must be purged
        assert TenantSafeCacheService.get(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='viewer',
            query='confidential audit'
        ) is None

    def test_tenant_safe_cache_isolation(self):
        """
        Verify tenant and role isolation in TenantSafeCacheService.
        """
        org2 = Organization.objects.create(name='Other Org', slug='other-org')
        ws2 = Workspace.objects.create(organization=org2, name='Other WS', slug='other-ws')

        # Store entry in ws1 for admin
        TenantSafeCacheService.set(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='what is the rule?',
            value={'result': 'ws1_admin_answer'}
        )

        # 1. Check cross-tenant isolation
        ws2_res = TenantSafeCacheService.get(
            org_id=str(org2.id),
            workspace_id=str(ws2.id),
            user_role='admin',
            query='what is the rule?'
        )
        assert ws2_res is None

        # 2. Check role isolation within same workspace
        viewer_res = TenantSafeCacheService.get(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='viewer',
            query='what is the rule?'
        )
        assert viewer_res is None

        # 3. Check invalidation of ws2 does not affect ws1
        TenantSafeCacheService.set(
            org_id=str(org2.id),
            workspace_id=str(ws2.id),
            user_role='admin',
            query='what is the rule?',
            value={'result': 'ws2_admin_answer'}
        )
        TenantSafeCacheService.invalidate_workspace(str(org2.id), str(ws2.id))

        assert TenantSafeCacheService.get(
            org_id=str(org2.id),
            workspace_id=str(ws2.id),
            user_role='admin',
            query='what is the rule?'
        ) is None

        assert TenantSafeCacheService.get(
            org_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            user_role='admin',
            query='what is the rule?'
        ) == {'result': 'ws1_admin_answer'}

    def test_store_reconciliation_service_missing_vectors(self):
        """
        Verify StoreReconciliationService detects and fixes missing vector embeddings in Qdrant.
        """
        job = IngestionJob.objects.create(
            document=self.doc1, organization=self.org, workspace=self.ws
        )
        process_ingestion_pipeline(str(job.id))
        self.doc1.refresh_from_db()
        assert self.doc1.status == 'ready'

        # Artificially wipe Qdrant vectors for doc1
        self.vstore.delete_document_chunks("lore_chunks", str(self.doc1.id))
        assert self.vstore.count_document_chunks("lore_chunks", str(self.doc1.id)) == 0

        # Dry run audit: should detect mismatch without fixing
        audit_res = StoreReconciliationService.reconcile(
            workspace_id=str(self.ws.id), fix=False
        )
        assert len(audit_res['mismatches']) >= 1
        mismatch = next(m for m in audit_res['mismatches'] if m['document_id'] == str(self.doc1.id))
        assert mismatch['fixed'] is False
        assert mismatch['qdrant_vector_count'] == 0
        assert mismatch['postgres_chunk_count'] > 0

        # Repair audit: should re-index vectors in Qdrant
        fix_res = StoreReconciliationService.reconcile(
            workspace_id=str(self.ws.id), fix=True
        )
        fixed_mismatch = next(m for m in fix_res['mismatches'] if m['document_id'] == str(self.doc1.id))
        assert fixed_mismatch['fixed'] is True
        assert self.vstore.count_document_chunks("lore_chunks", str(self.doc1.id)) > 0

        # Subsequent audit: should be healthy
        healthy_res = StoreReconciliationService.reconcile(
            workspace_id=str(self.ws.id), fix=False
        )
        assert len(healthy_res['mismatches']) == 0

    def test_store_reconciliation_orphaned_vectors(self):
        """
        Verify StoreReconciliationService purges orphaned vectors in Qdrant whose
        associated documents do not exist in PostgreSQL.
        """
        fake_doc_id = str(uuid.uuid4())
        # Insert orphan points into Qdrant
        self.vstore.upsert_chunks(
            collection_name="lore_chunks",
            vectors=[[0.05] * 384],
            payloads=[{
                'chunk_id': str(uuid.uuid4()),
                'document_id': fake_doc_id,
                'document_title': 'Orphan Spec',
                'organization_id': str(self.org.id),
                'workspace_id': str(self.ws.id),
                'page_number': 1,
                'heading_path': '',
                'authority_level': 3,
                'text': 'Orphan text'
            }],
            ids=[str(uuid.uuid4())]
        )

        assert self.vstore.count_document_chunks("lore_chunks", fake_doc_id) == 1

        # Reconcile with fix=True
        res = StoreReconciliationService.reconcile(fix=True)
        orphan_entry = next((o for o in res['orphans'] if o['document_id'] == fake_doc_id), None)
        assert orphan_entry is not None
        assert orphan_entry['fixed'] is True

        # Orphan should now be purged
        assert self.vstore.count_document_chunks("lore_chunks", fake_doc_id) == 0

    def test_generic_connector_contract(self):
        """
        Verify BaseConnector contract and SyncCheckpoint / SyncResult functionality.
        """
        class MockDriveConnector(BaseConnector):
            @property
            def connector_type(self) -> str:
                return 'google_drive'

            def test_connection(self) -> bool:
                return True

            def fetch_document_content(self, external_id: str) -> bytes:
                return b"mock file content"

            def list_events(self, checkpoint=None, full_sync=False):
                # Yield 2 events
                yield SyncEvent(
                    event_type='create',
                    external_id='ext-001',
                    source_type='google_drive',
                    title='Quarterly Earnings',
                    mime_type='application/pdf',
                    file_bytes=b"content-1"
                )
                yield SyncEvent(
                    event_type='update',
                    external_id='ext-002',
                    source_type='google_drive',
                    title='Org Chart',
                    mime_type='application/pdf',
                    file_bytes=b"content-2"
                )
                return SyncCheckpoint(cursor='cursor-102', last_synced_at='2026-10-23T00:00:00Z')

        connector = MockDriveConnector(
            organization_id=str(self.org.id),
            workspace_id=str(self.ws.id),
            config={'rate_limit_delay_seconds': 0.0}
        )

        assert connector.test_connection() is True
        result = connector.sync(full_sync=True)

        assert result.success is True
        assert result.events_detected == 2
        assert result.documents_created == 1
        assert result.documents_updated == 1
        assert result.next_checkpoint is not None
        assert result.next_checkpoint.cursor == 'cursor-102'
