import logging
from typing import Dict, Any, Optional, List
from django.utils import timezone
from apps.sources.models import SourceDocument
from apps.knowledge.models import DocumentChunk
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.embeddings import get_embedding_adapter
from apps.audit.models import AuditEvent

logger = logging.getLogger(__name__)

class StoreReconciliationService:
    """
    Enterprise Data Store Reconciliation Service (P2).
    Verifies and repairs cross-store consistency between PostgreSQL (canonical truth)
    and Qdrant (derived vector store).
    """

    @classmethod
    def reconcile(
        cls,
        workspace_id: Optional[str] = None,
        fix: bool = False,
        collection_name: str = "lore_chunks"
    ) -> Dict[str, Any]:
        """
        Executes cross-store audit between PostgreSQL chunks and Qdrant vectors.
        
        Args:
            workspace_id: Optional workspace UUID string to restrict audit.
            fix: If True, repairs discrepancies by re-indexing missing vectors or purging orphaned vectors.
            collection_name: Qdrant collection name.
        """
        vstore = QdrantVectorStore()
        summary = {
            'total_documents_checked': 0,
            'healthy_documents': 0,
            'mismatches': [],
            'orphans': [],
            'fixed_count': 0,
            'timestamp': timezone.now().isoformat()
        }

        # 1. Audit published documents in PostgreSQL
        doc_qs = SourceDocument.objects.filter(status__in=['ready', 'needs_review'])
        if workspace_id:
            doc_qs = doc_qs.filter(workspace_id=workspace_id)

        doc_ids_checked = set()

        for doc in doc_qs.iterator():
            summary['total_documents_checked'] += 1
            doc_id_str = str(doc.id)
            doc_ids_checked.add(doc_id_str)

            pg_chunks = list(DocumentChunk.objects.filter(document=doc).order_by('chunk_index'))
            pg_chunk_count = len(pg_chunks)
            qdrant_vector_count = vstore.count_document_chunks(collection_name, doc_id_str)

            if pg_chunk_count == qdrant_vector_count and pg_chunk_count > 0:
                summary['healthy_documents'] += 1
            else:
                mismatch_info = {
                    'document_id': doc_id_str,
                    'title': doc.title,
                    'postgres_chunk_count': pg_chunk_count,
                    'qdrant_vector_count': qdrant_vector_count,
                    'status': doc.status,
                    'fixed': False
                }

                if fix and pg_chunk_count > 0:
                    try:
                        # Purge mismatched vectors and re-index
                        vstore.delete_document_chunks(collection_name, doc_id_str)
                        embedder = get_embedding_adapter()
                        embed_texts = [f"{c.contextual_header}\n---\n{c.text}" for c in pg_chunks]
                        vectors = embedder.embed_batch(embed_texts)
                        ids = [str(c.id) for c in pg_chunks]
                        payloads = [
                            {
                                'chunk_id': str(c.id),
                                'document_id': doc_id_str,
                                'document_version': doc.current_version_number,
                                'document_title': doc.title,
                                'organization_id': str(doc.organization_id),
                                'workspace_id': str(doc.workspace_id),
                                'collection_id': str(doc.collection_id) if doc.collection_id else "",
                                'page_number': c.page_number,
                                'heading_path': c.heading_path,
                                'authority_level': doc.authority_level,
                                'text': c.text[:300]
                            }
                            for c in pg_chunks
                        ]
                        vstore.upsert_chunks(
                            collection_name=collection_name,
                            vectors=vectors,
                            payloads=payloads,
                            ids=ids
                        )
                        for idx, c in enumerate(pg_chunks):
                            c.vector_id = ids[idx]
                            c.save(update_fields=['vector_id'])

                        mismatch_info['fixed'] = True
                        summary['fixed_count'] += 1

                        AuditEvent.objects.create(
                            organization=doc.organization,
                            workspace=doc.workspace,
                            event_type='store_reconciled',
                            target_type='document',
                            target_id=doc_id_str,
                            details={
                                'action': 'reindexed_missing_vectors',
                                'postgres_chunk_count': pg_chunk_count,
                                'previous_vector_count': qdrant_vector_count
                            }
                        )
                    except Exception as err:
                        logger.exception(f"Failed to repair vector discrepancy for doc {doc_id_str}: {err}")
                        mismatch_info['repair_error'] = str(err)

                summary['mismatches'].append(mismatch_info)

        # 2. Audit orphaned vectors in Qdrant (vectors that reference deleted or inactive documents)
        try:
            indexed_doc_ids = vstore.list_indexed_document_ids(collection_name)
            for indexed_id in indexed_doc_ids:
                # If scoped to a specific workspace and this doc was checked, it's valid; otherwise check DB
                if indexed_id in doc_ids_checked:
                    continue

                active_doc_exists = SourceDocument.objects.filter(
                    id=indexed_id,
                    status__in=['ready', 'needs_review']
                ).exists()

                if not active_doc_exists:
                    orphan_info = {
                        'document_id': indexed_id,
                        'reason': 'document_missing_or_inactive_in_postgres',
                        'fixed': False
                    }
                    if fix:
                        try:
                            vstore.delete_document_chunks(collection_name, indexed_id)
                            orphan_info['fixed'] = True
                            summary['fixed_count'] += 1
                            logger.info(f"Purged orphaned vectors in Qdrant for doc {indexed_id}")
                        except Exception as oerr:
                            logger.exception(f"Failed to purge orphan doc {indexed_id}: {oerr}")
                            orphan_info['purge_error'] = str(oerr)

                    summary['orphans'].append(orphan_info)

        except Exception as qerr:
            logger.warning(f"Could not audit orphaned vectors in Qdrant: {qerr}")

        return summary
