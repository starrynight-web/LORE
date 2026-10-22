import logging
import re
from typing import List, Dict, Any, Optional
from apps.knowledge.models import DocumentChunk
from apps.sources.models import SourceDocument
from .vector_store import QdrantVectorStore
from .embeddings import get_embedding_adapter

logger = logging.getLogger(__name__)


class _RerankDescriptor:
    def __get__(self, instance, owner):
        if instance is not None:
            def instance_rerank(query, candidates, top_k=10, min_relevance_threshold=None):
                thresh = min_relevance_threshold if min_relevance_threshold is not None else instance.min_relevance_threshold
                return owner._do_rerank(query, candidates, top_k=top_k, min_relevance_threshold=thresh)
            return instance_rerank
        else:
            def class_rerank(query, candidates, top_k=10, min_relevance_threshold=0.05):
                return owner._do_rerank(query, candidates, top_k=top_k, min_relevance_threshold=min_relevance_threshold)
            return class_rerank


class ContextReranker:
    """
    Reranks hybrid search candidates purely on semantic and lexical relevance:
    1. Exact phrase and n-gram overlap with the query.
    2. Token coverage across chunk body and contextual headers.
    3. Dense vector + BM25 Reciprocal Rank Fusion (RRF) normalized seed score.
    4. Positional density and contextual heading relevance.

    CRITICAL ARCHITECTURAL INVARIANT:
    Authority must NOT turn irrelevant or out-of-scope evidence into a valid decision.
    Ranking scores ONLY reflect relevance to the query. Governance filters (L7 permissions,
    L5 temporal validity, L4 scoped exceptions, publication state) and L6 authority conflict
    arbitration must remain strictly separate from retrieval ranking.
    """

    def __init__(self, min_relevance_threshold: float = 0.05):
        self.min_relevance_threshold = min_relevance_threshold

    rerank = _RerankDescriptor()

    @classmethod
    def _do_rerank(
        cls,
        query: str,
        candidates: List[Any],
        top_k: int = 10,
        min_relevance_threshold: float = 0.05
    ) -> List[Any]:
        if not candidates:
            return []

        q_clean = query.strip().lower()
        q_tokens = set([w for w in re.findall(r'\w+', q_clean) if len(w) > 1])

        scored_candidates = []
        raw_scores = []
        for item in candidates:
            if isinstance(item, tuple) and len(item) > 0:
                raw_scores.append(item[0])
            elif isinstance(item, dict):
                raw_scores.append(item.get('rrf_score', 0.5))
        max_rrf = max(raw_scores) if raw_scores else 1.0

        for item in candidates:
            if isinstance(item, tuple):
                is_tuple = True
                rrf_score = item[0]
                chk = item[1]
                text = (getattr(chk, 'text', '') or '').lower()
                header = (getattr(chk, 'contextual_header', '') or '').lower()
                heading = (getattr(chk, 'heading_path', '') or '').lower()
                doc = getattr(chk, 'document', None)
                title = (getattr(doc, 'title', '') or '').lower() if doc else ''
                auth_rank = getattr(doc, 'authority_level', 3) if doc else 3
            elif isinstance(item, dict):
                is_tuple = False
                chk = item
                rrf_score = item.get('rrf_score', 0.5)
                text = (item.get('text', '') or '').lower()
                header = (item.get('contextual_header', '') or item.get('heading', '') or '').lower()
                heading = (item.get('heading_path', '') or item.get('heading', '') or '').lower()
                title = (item.get('document_title', '') or '').lower()
                auth_rank = item.get('authority_level', 3)
            else:
                continue

            # 1. Normalized RRF component [0, 1]
            norm_rrf = rrf_score / (max_rrf if max_rrf > 0 else 1.0)

            # 2. Exact phrase match bonus
            phrase_bonus = 0.0
            if len(q_clean) > 3 and (q_clean in text or q_clean in header or q_clean in title):
                phrase_bonus = 0.35

            # 3. Token coverage score [0, 1]
            if q_tokens:
                matched_tokens = sum(1 for t in q_tokens if t in text or t in header or t in heading or t in title)
                token_coverage = matched_tokens / len(q_tokens)
            else:
                token_coverage = 0.0

            # 4. Contextual header relevance bonus
            header_bonus = 0.0
            if header and any(t in header for t in q_tokens):
                header_bonus = 0.15

            # 5. Pure relevance score (DO NOT MULTIPLY BY AUTHORITY!)
            if token_coverage == 0.0 and phrase_bonus == 0.0 and header_bonus == 0.0:
                relevance_score = 0.08 * norm_rrf
            else:
                relevance_score = (0.45 * norm_rrf) + (0.35 * token_coverage) + phrase_bonus + header_bonus

            # Threshold gating: completely irrelevant chunks are not promoted
            if relevance_score < min_relevance_threshold:
                continue

            meta = {
                'relevance_score': round(relevance_score, 4),
                'rrf_score': round(rrf_score, 4),
                'token_coverage': round(token_coverage, 2),
                'phrase_match': bool(phrase_bonus > 0),
                'authority_level': auth_rank
            }

            if is_tuple:
                scored_candidates.append((relevance_score, chk, meta))
            else:
                res_dict = dict(item)
                res_dict['score'] = round(relevance_score, 4)
                res_dict.update(meta)
                scored_candidates.append(res_dict)

        # Sort descending purely by relevance score
        if scored_candidates and isinstance(scored_candidates[0], tuple):
            scored_candidates.sort(key=lambda x: x[0], reverse=True)
        else:
            scored_candidates.sort(key=lambda x: x.get('score', 0.0), reverse=True)

        return scored_candidates[:top_k]


class HybridRetrievalService:
    """
    10-stage Retrieval Engine with Hybrid Search & Context Reranker:
    - Stage 0: Strict tenant and workspace boundary filtering (organization_id & workspace_id)
    - Stage 2: Hybrid seed (Dense Qdrant vector search + Lexical DB search)
    - Fusion: Reciprocal Rank Fusion (RRF k=60)
    - Stage 4: Authority ladder weighting (approved policy > wiki > informal note)
    - Stage 6: Context Reranking via phrase matching & token coverage
    - Stage 9: Context budgeting (≤800 tokens / top candidates)
    """

    def __init__(self, vector_store: Optional[QdrantVectorStore] = None):
        self.vector_store = vector_store or QdrantVectorStore()
        self.embedder = get_embedding_adapter()

    def search(
        self,
        query: str,
        workspace_id: str,
        organization_id: str,
        collection_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 8
    ) -> List[Dict[str, Any]]:
        if not query.strip():
            return []

        # 1. Dense Vector Search via Qdrant with Strict Tenant & Document Isolation
        query_vec = self.embedder.embed_text(query)
        qdrant_filter = {
            "workspace_id": str(workspace_id),
            "organization_id": str(organization_id)
        }
        if collection_id:
            qdrant_filter["collection_id"] = str(collection_id)
        if document_id:
            qdrant_filter["document_id"] = str(document_id)

        from apps.retrieval.resilience import resilient_vector_search

        vector_hits = resilient_vector_search(
            vector_store=self.vector_store,
            collection_name="lore_chunks",
            query_vector=query_vec,
            filter_dict=qdrant_filter,
            limit=25,
            workspace_id=str(workspace_id) if workspace_id else None,
            query_text=query
        )

        vector_ranks = {}
        for rank, hit in enumerate(vector_hits):
            cid = hit['payload'].get('chunk_id')
            if cid:
                vector_ranks[cid] = rank + 1

        # 2. Lexical Keyword & Substring Search in Database (Bengali + English)
        # Stable-only serving (lore.md §6): Exclude quarantined, draft, or failed documents
        keywords = [w for w in re.findall(r'\w+', query.lower()) if len(w) > 1]
        lexical_qs = DocumentChunk.objects.filter(
            workspace_id=workspace_id,
            organization_id=organization_id,
            document__status='ready'
        ).exclude(
            document__status__in=['quarantined', 'failed', 'needs_review', 'uploaded']
        )
        if collection_id:
            lexical_qs = lexical_qs.filter(document__collection_id=collection_id)
        if document_id:
            lexical_qs = lexical_qs.filter(document_id=document_id)

        # Lexical matching over chunks
        lexical_chunk_ids = set()
        for kw in keywords[:6]:
            matches = list(lexical_qs.filter(text__icontains=kw).values_list('id', flat=True)[:20])
            lexical_chunk_ids.update(matches)

        lexical_chunks = list(
            DocumentChunk.objects.filter(id__in=lexical_chunk_ids).select_related('document')[:25]
        )
        lexical_ranks = {}
        for rank, chk in enumerate(lexical_chunks):
            lexical_ranks[str(chk.id)] = rank + 1

        # 3. Reciprocal Rank Fusion (RRF, k=60)
        all_chunk_ids = set(vector_ranks.keys()) | set(lexical_ranks.keys())

        # If no relevant chunks matched vector or lexical seeds, return empty list
        # Do NOT inject random high-authority chunks; authority must never fabricate relevance.
        if not all_chunk_ids:
            return []

        # Fetch chunk database models with relations
        chunks_map = {
            str(c.id): c for c in DocumentChunk.objects.filter(
                id__in=all_chunk_ids
            ).select_related('document', 'document__collection', 'document_version')
        }

        rrf_candidates = []
        k = 60.0

        for cid in all_chunk_ids:
            chk = chunks_map.get(cid)
            if not chk:
                continue

            r_vec = vector_ranks.get(cid, 999)
            r_lex = lexical_ranks.get(cid, 999)

            score = (1.0 / (k + r_vec)) + (1.0 / (k + r_lex))
            rrf_candidates.append((score, chk))

        # 4. Context Reranking Stage
        reranked_candidates = ContextReranker.rerank(
            query=query,
            candidates=rrf_candidates,
            top_k=max(limit * 2, 16)
        )

        # 5. Context Budgeting: ≤800 tokens
        budget = 800
        accumulated_tokens = 0
        final_results = []

        for final_score, chk, meta in reranked_candidates:
            chk_tokens = chk.token_count or len((chk.text or '').split())
            if accumulated_tokens + chk_tokens > budget and final_results:
                break

            accumulated_tokens += chk_tokens
            ver_num = chk.document_version.version_number if chk.document_version else chk.document.current_version_number
            final_results.append({
                'chunk_id': str(chk.id),
                'document_id': str(chk.document.id),
                'document_title': chk.document.title,
                'document_type': chk.document.document_type,
                'document_version': ver_num,
                'page_number': chk.page_number,
                'heading_path': chk.heading_path,
                'text': chk.text,
                'contextual_header': chk.contextual_header,
                'authority_level': chk.document.authority_level,
                'score': round(final_score, 4),
                'rrf_score': meta.get('rrf_score', 0),
                'token_coverage': meta.get('token_coverage', 0),
                'phrase_match': meta.get('phrase_match', False),
                'token_count': chk_tokens,
            })

            if len(final_results) >= limit:
                break

        return final_results

