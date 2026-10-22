"""
LORE Enterprise — Source Document & Governance Signals
Specification: Master Prompt P2 §12 (Source synchronization and deletion) & §13 (Tenant-safe cache correctness).

Enforces automatic cascading cleanup across stores whenever documents or permissions change:
1. Deleting a SourceDocument automatically purges vectors from Qdrant, deletes storage files,
   and invalidates tenant-safe cache keys.
2. Modifying or deleting SourcePermission automatically invalidates the workspace query cache,
   preventing unauthorized data from leaking through stale cached responses.
"""

import os
import logging
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from apps.sources.models import SourceDocument
from apps.governance.models import SourcePermission
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.cache import TenantSafeCacheService
from apps.audit.models import AuditEvent

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=SourceDocument)
def on_source_document_deleted(sender, instance, **kwargs):
    """
    Cascading cleanup across derived stores when a canonical SourceDocument is deleted.
    """
    doc_id = str(instance.id)
    ws_id = str(instance.workspace_id)
    org = instance.organization
    ws = instance.workspace

    # 1. Purge vectors from Qdrant vector store
    try:
        vstore = QdrantVectorStore()
        vstore.delete_document_chunks("lore_chunks", doc_id)
        logger.info(f"[Cascade Delete] Purged vectors for document {doc_id} from Qdrant.")
    except Exception as ex:
        logger.warning(f"[Cascade Delete] Could not delete vectors for document {doc_id}: {ex}")

    # 2. Invalidate tenant-safe caches for workspace
    try:
        TenantSafeCacheService.invalidate_document(ws_id, doc_id)
    except Exception as ex:
        logger.warning(f"[Cascade Delete] Cache invalidation error for document {doc_id}: {ex}")

    # 3. Clean up physical file on disk
    try:
        if instance.file_obj and hasattr(instance.file_obj, 'path') and os.path.exists(instance.file_obj.path):
            os.remove(instance.file_obj.path)
            logger.info(f"[Cascade Delete] Removed file on disk: {instance.file_obj.path}")
    except Exception as ex:
        logger.warning(f"[Cascade Delete] Could not remove file on disk: {ex}")

    # 4. Record audit trail
    try:
        AuditEvent.objects.create(
            organization=org,
            workspace=ws,
            event_type='item_deleted',
            target_type='document',
            target_id=doc_id,
            details={
                'title': instance.title,
                'file_hash': instance.file_hash,
                'deleted_from': 'canonical_post_delete_signal'
            }
        )
    except Exception as ex:
        logger.warning(f"[Cascade Delete] Could not create audit event: {ex}")


@receiver(post_save, sender=SourcePermission)
@receiver(post_delete, sender=SourcePermission)
def on_source_permission_changed(sender, instance, **kwargs):
    """
    Immediate cache invalidation when document access permissions change.
    Guarantees no stale authorized answers remain in cache after permission revocation.
    """
    try:
        doc = instance.document
        if doc and doc.workspace_id:
            ws_id = str(doc.workspace_id)
            TenantSafeCacheService.invalidate_workspace(ws_id)
            logger.info(f"[Permission Propagation] Invalidated cache for workspace {ws_id} on permission change.")

            AuditEvent.objects.create(
                organization=doc.organization,
                workspace=doc.workspace,
                event_type='permission_changed',
                target_type='permission',
                target_id=str(instance.id),
                details={
                    'document_id': str(doc.id),
                    'access_level': getattr(instance, 'access_level', 'internal'),
                    'allowed_roles': getattr(instance, 'allowed_roles', [])
                }
            )
    except Exception as ex:
        logger.warning(f"[Permission Propagation] Error handling permission signal: {ex}")
