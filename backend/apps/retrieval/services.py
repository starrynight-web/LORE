import logging
from typing import List, Dict, Any, Optional
from apps.knowledge.models import DocumentChunk
from apps.sources.models import SourceDocument
from .vector_store import QdrantVectorStore
from .embeddings import LocalEmbeddingService

logger = logging.getLogger(__name__)

class HybridRetrievalService:
    """
    10-stage Retrieval Engine from lore.md:
    - Stage 0: Strict tenant and workspace boundary filtering
    - Stage 2: Hybrid seed (Dense Qdrant vector search + Lexical search)
    - Fusion: Reciprocal Rank Fusion (RRF k=60)
    - Stage 4: Authority ladder weighting (approved policy > wiki > informal note)
    - Stage 9: Context budgeting (≤800 tokens / top candidates)
    """

    def __init__(self, vector_store: Optional[QdrantVectorStore] = None):
        self.vector_store = vector_store or QdrantVectorStore()
        self.embedder = LocalEmbeddingService()

    def search(
        self,
        query: str,
        workspace_id: str,
        organization_id: str,
        collection_id: Optional[str] = None,
        limit: int = 8
    ) -> List[Dict[str, Any]]:
        if not query.strip():
            return []

        # 1. Dense Vector Search via Qdrant
        query_vec = self.embedder.embed_text(query)
        qdrant_filter = {"workspace_id": str(workspace_id)}
        if collection_id:
            qdrant_filter["collection_id"] = str(collection_id)

        vector_hits = self.vector_store.search(
            collection_name="lore_chunks",
            query_vector=query_vec,
            filter_dict=qdrant_filter,
            limit=20
        )

        vector_ranks = {}
        for rank, hit in enumerate(vector_hits):
            cid = hit['payload'].get('chunk_id')
            if cid:
                vector_ranks[cid] = rank + 1

        # 2. Lexical Keyword Search in Database
        keywords = [w for w in query.lower().split() if len(w) > 2]
        lexical_qs = DocumentChunk.objects.filter(
            workspace_id=workspace_id,
            organization_id=organization_id,
            document__status='ready'
        )
        if collection_id:
            lexical_qs = lexical_qs.filter(document__collection_id=collection_id)

        for kw in keywords[:4]:
            lexical_qs = lexical_qs.filter(text__icontains=kw)

        lexical_chunks = list(lexical_qs[:20])
        lexical_ranks = {}
        for rank, chk in enumerate(lexical_chunks):
            lexical_ranks[str(chk.id)] = rank + 1

        # 3. Reciprocal Rank Fusion (RRF, k=60)
        all_chunk_ids = set(vector_ranks.keys()) | set(lexical_ranks.keys())

        if not all_chunk_ids:
            # Fallback: simple text match if strict fusion has no overlap
            fallback_qs = DocumentChunk.objects.filter(
                workspace_id=workspace_id,
                organization_id=organization_id,
                document__status='ready'
            ).order_by('-document__authority_level')[:limit]
            all_chunk_ids = {str(c.id) for c in fallback_qs}

        # Fetch chunk database models
        chunks_map = {
            str(c.id): c for c in DocumentChunk.objects.filter(
                id__in=all_chunk_ids
            ).select_related('document', 'document__collection')
        }

        rrf_scores = []
        k = 60.0

        for cid in all_chunk_ids:
            chk = chunks_map.get(cid)
            if not chk:
                continue

            r_vec = vector_ranks.get(cid, 999)
            r_lex = lexical_ranks.get(cid, 999)

            score = (1.0 / (k + r_vec)) + (1.0 / (k + r_lex))

            # Authority Ladder Boost (Rank 1 to 7)
            auth_rank = chk.document.authority_level
            authority_multiplier = 1.0 + (auth_rank * 0.08)
            final_score = score * authority_multiplier

            rrf_scores.append((final_score, chk))

        # Sort descending by score
        rrf_scores.sort(key=lambda x: x[0], reverse=True)

        # Context Budgeting: ≤800 tokens
        budget = 800
        accumulated_tokens = 0
        final_results = []

        for score, chk in rrf_scores:
            chk_tokens = chk.token_count or len(chk.text.split())
            if accumulated_tokens + chk_tokens > budget and final_results:
                break

            accumulated_tokens += chk_tokens
            final_results.append({
                'chunk_id': str(chk.id),
                'document_id': str(chk.document.id),
                'document_title': chk.document.title,
                'document_type': chk.document.document_type,
                'document_version': chk.document.current_version_number,
                'page_number': chk.page_number,
                'heading_path': chk.heading_path,
                'text': chk.text,
                'contextual_header': chk.contextual_header,
                'authority_level': chk.document.authority_level,
                'score': round(score, 4),
                'token_count': chk_tokens,
            })

            if len(final_results) >= limit:
                break

        return final_results
