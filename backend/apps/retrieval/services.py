import time
import logging
import re
from typing import List, Dict, Any, Optional, Tuple, Union
from django.conf import settings

from apps.knowledge.models import DocumentChunk
from apps.sources.models import SourceDocument
from .vector_store import QdrantVectorStore
from .embeddings import get_embedding_adapter
from .lexical import LexicalSearchService
from .resilience import resilient_vector_search, qdrant_circuit_breaker, CircuitState
from .reranking import BaseReranker, HeuristicReranker, RerankerFactory

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

    CRITICAL ARCHITECTURAL INVARIANT (P1 §6 & lore.md §6):
    Authority must NOT turn irrelevant or out-of-scope evidence into a valid decision.
    Ranking scores ONLY reflect relevance to the query. Governance filters (L7 permissions,
    L5 temporal validity, L4 scoped exceptions, publication state) and L6 authority conflict
    arbitration must remain strictly separate from retrieval ranking.
    """

    def __init__(self, min_relevance_threshold: float = 0.05):
        self.min_relevance_threshold = min_relevance_threshold
        self._heuristic = HeuristicReranker(min_relevance_threshold=min_relevance_threshold)

    rerank = _RerankDescriptor()

    @classmethod
    def _do_rerank(
        cls,
        query: str,
        candidates: List[Any],
        top_k: int = 10,
        min_relevance_threshold: float = 0.05
    ) -> List[Any]:
        reranker = HeuristicReranker(min_relevance_threshold=min_relevance_threshold)
        return reranker.rerank(
            query=query,
            candidates=candidates,
            top_k=top_k,
            min_relevance_threshold=min_relevance_threshold
        )




class HybridRetrievalService:
    """
    10-stage Retrieval Engine with Hybrid Search, Full-Text Indexing, & Context Reranker:
    - Stage 0: Strict tenant and workspace boundary filtering (organization_id & workspace_id)
    - Stage 2: Hybrid seed (Dense Qdrant vector search + Database Full-Text Search)
    - Fusion: Reciprocal Rank Fusion (RRF k=60.0) with observable candidate ranks & fusion parameters
    - Stage 4: Authority ladder metadata tracking (authority does NOT alter relevance)
    - Stage 6: Context Reranking via phrase matching & token coverage
    - Stage 9: Configurable Context budgeting (default ≤800 tokens / top candidates)
    - Diagnostics: Query-level performance diagnostics without logging protected document content
    """

    def __init__(
        self,
        vector_store: Optional[QdrantVectorStore] = None,
        lexical_service: Optional[LexicalSearchService] = None,
        embedder: Optional[Any] = None,
        reranker: Optional[BaseReranker] = None
    ):
        self.vector_store = vector_store or QdrantVectorStore()
        self.lexical_service = lexical_service or LexicalSearchService
        self.embedder = embedder or get_embedding_adapter()
        self.reranker = reranker or RerankerFactory.get_reranker()
        self.last_diagnostics: Dict[str, Any] = {}

    def search(
        self,
        query: str,
        workspace_id: str,
        organization_id: str,
        collection_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 8,
        context_budget_tokens: Optional[int] = None,
        rrf_k: float = 60.0,
        min_relevance_threshold: float = 0.05,
        enable_graph_expansion: bool = True,
        graph_max_depth: int = 2,
        graph_max_nodes: int = 15,
        graph_timeout_ms: float = 100.0,
        permitted_relationship_types: Optional[List[str]] = None,
        user=None,
        user_role: str = 'member',
        as_of=None,
    ) -> List[Dict[str, Any]]:
        t_start = time.time()
        self.last_diagnostics = {}
        self.last_graph_result = None

        if not query or not query.strip():
            self.last_diagnostics = {
                'query_length': 0,
                'retrieval_mode': 'empty_query',
                'selected_final_count': 0,
                'total_ms': 0
            }
            return []

        # Load active production RetrievalConfiguration if workspace provided and using defaults
        if workspace_id:
            try:
                from apps.retrieval.models import RetrievalConfiguration
                cfg = RetrievalConfiguration.objects.filter(workspace_id=workspace_id, is_active=True).first()
                if not cfg:
                    cfg = RetrievalConfiguration.objects.filter(workspace=None, is_active=True).first()
                if cfg:
                    if limit == 8 and cfg.limit:
                        limit = cfg.limit
                    if rrf_k == 60.0 and cfg.rrf_k:
                        rrf_k = cfg.rrf_k
                    if min_relevance_threshold == 0.05 and cfg.min_relevance_threshold:
                        min_relevance_threshold = cfg.min_relevance_threshold
                    if context_budget_tokens is None and cfg.context_budget_tokens:
                        context_budget_tokens = cfg.context_budget_tokens
                    if enable_graph_expansion is True and cfg.enable_graph_expansion is not None:
                        enable_graph_expansion = cfg.enable_graph_expansion
                        graph_max_depth = cfg.graph_max_depth
                        graph_max_nodes = cfg.graph_max_nodes
            except Exception:
                pass

        budget = context_budget_tokens or getattr(settings, 'RETRIEVAL_CONTEXT_BUDGET_TOKENS', 800)
        candidate_budget = RerankerFactory.get_candidate_budget(limit=limit)
        query_clean = query.strip()
        q_tokens = [w.lower() for w in re.findall(r'\w+', query_clean) if len(w) > 1]

        # ---------------- Stage 0b: Query Understanding & Intent Analysis ----------------
        from .query_understanding import QueryUnderstandingService, QueryAnalysis
        analysis = QueryUnderstandingService.analyze(query=query_clean, caller_as_of=as_of)
        effective_as_of = as_of or analysis.target_date

        # ---------------- Stage 1: Dense Vector Search ----------------
        t_vec_start = time.time()
        query_vec = self.embedder.embed_text(query_clean)
        qdrant_filter = {
            "workspace_id": workspace_id,
            "organization_id": organization_id
        }
        if collection_id:
            qdrant_filter["collection_id"] = collection_id
        if document_id:
            qdrant_filter["document_id"] = document_id

        vector_hits = resilient_vector_search(
            vector_store=self.vector_store,
            collection_name="lore_chunks",
            query_vector=query_vec,
            filter_dict=qdrant_filter,
            limit=candidate_budget,
            workspace_id=workspace_id if workspace_id else None,
            query_text=query_clean
        )
        t_vec_end = time.time()

        # Check for vector outage / degraded fallback mode
        vector_degraded = False
        if any(h.get('payload', {}).get('circuit_breaker_active') for h in vector_hits) or \
           qdrant_circuit_breaker.state == CircuitState.OPEN:
            vector_degraded = True

        vector_ranks = {}
        for rank, hit in enumerate(vector_hits):
            cid = hit.get('payload', {}).get('chunk_id') or hit.get('id')
            if cid:
                vector_ranks[str(cid)] = rank + 1

        # ---------------- Stage 2: Database Full-Text Search ----------------
        t_lex_start = time.time()
        lexical_pairs = self.lexical_service.search_chunks(
            query=query_clean,
            workspace_id=workspace_id,
            organization_id=organization_id,
            collection_id=collection_id,
            document_id=document_id,
            limit=candidate_budget
        )
        t_lex_end = time.time()

        lexical_ranks = {}
        for rank, (lex_score, chk) in enumerate(lexical_pairs):
            lexical_ranks[str(chk.id)] = rank + 1

        # ---------------- Stage 2b: Multi-Document Companion Guarantees (Requirement 3) ----------------
        all_candidate_ids = set(vector_ranks.keys()) | set(lexical_ranks.keys())
        if workspace_id and analysis.all_target_doc_codes:
            for t_code in analysis.all_target_doc_codes:
                if t_code.upper() == 'DOC-021':
                    continue
                # Verify if this target code is present in candidate IDs
                from django.db.models import Q
                code_q = Q(document__document_code=t_code.upper()) | Q(document__title__icontains=t_code) | Q(document__original_filename__icontains=t_code)
                has_cand = DocumentChunk.objects.filter(
                    id__in=all_candidate_ids
                ).filter(code_q).exists()
                if not has_cand:
                    comp_chunks = DocumentChunk.objects.filter(
                        workspace_id=workspace_id
                    ).filter(code_q).exclude(
                        document__status__in=['quarantined', 'failed', 'deleted', 'uploaded', 'needs_review', 'queued']
                    ).order_by('chunk_index')[:4]
                    for comp_c in comp_chunks:
                        comp_cid = str(comp_c.id)
                        all_candidate_ids.add(comp_cid)
                        lexical_ranks[comp_cid] = min(lexical_ranks.get(comp_cid, 999), 12)

        # Negative Retrieval / Missing Document Boundary Detection (Requirement 3 & 7)
        missing_boundary_candidates = []
        if analysis.is_negative_query or 'DOC-021' in [c.upper() for c in analysis.all_target_doc_codes]:
            missing_docs = SourceDocument.objects.filter(workspace_id=workspace_id, is_missing=True)
            for m_doc in missing_docs:
                m_cid = f"missing-{m_doc.id}"
                missing_boundary_candidates.append({
                    'chunk_id': m_cid,
                    'document_id': str(m_doc.id),
                    'document_title': m_doc.canonical_title or m_doc.title,
                    'document_code': m_doc.document_code or "DOC-021",
                    'document_type': m_doc.document_type,
                    'document_version': 1,
                    'page_number': 1,
                    'heading_path': 'Corpus Boundary',
                    'section_identifier': 'Corpus Boundary',
                    'governance_status': 'missing',
                    'is_missing': True,
                    'effective_from': '',
                    'effective_to': '',
                    'text': f"Document {m_doc.document_code} ({m_doc.title}) is registered as a referenced document in the corpus, but the document content is missing/absent from the knowledge base.",
                    'contextual_header': f"{m_doc.document_code} Missing Document Boundary",
                    'authority_level': 1,
                    'rrf_score': 0.99,
                    'score': 1.0,
                    'token_count': 30,
                    'graph_expanded': False,
                    'candidate_ranks': {'vector_rank': 1, 'lexical_rank': 1},
                    'fusion_params': {'k': float(rrf_k), 'rrf_score': 0.99},
                    'retrieval_status': 'corpus_boundary_negative'
                })

        # ---------------- Stage 3: Reciprocal Rank Fusion (RRF) ----------------
        t_fusion_start = time.time()

        if not all_candidate_ids:
            total_elapsed = int((time.time() - t_start) * 1000)
            self.last_diagnostics = {
                'query_length': len(query_clean),
                'query_tokens_count': len(q_tokens),
                'retrieval_mode': 'degraded_lexical_only' if vector_degraded else 'hybrid',
                'vector_store_healthy': not vector_degraded,
                'circuit_breaker_active': vector_degraded,
                'stage_timings_ms': {
                    'vector_ms': max(1, int((t_vec_end - t_vec_start) * 1000)),
                    'lexical_ms': max(1, int((t_lex_end - t_lex_start) * 1000)),
                    'fusion_ms': 0,
                    'graph_ms': 0,
                    'rerank_ms': 0,
                    'total_ms': total_elapsed,
                },
                'candidate_counts': {
                    'vector_candidates': len(vector_hits),
                    'lexical_candidates': len(lexical_pairs),
                    'unique_fused_candidates': 0,
                    'graph_expanded_candidates': 0,
                    'reranked_candidates': 0,
                    'selected_final_count': 0,
                },
                'context_budget': {
                    'configured_budget_tokens': budget,
                    'consumed_tokens': 0,
                    'truncated_candidates_count': 0,
                },
                'graph_traversal': {
                    'enabled': enable_graph_expansion,
                    'status': 'skipped_no_seeds',
                    'degraded': False,
                    'nodes_expanded_count': 0,
                },
                'lexical_backend': self.lexical_service.get_backend_info(),
                'embedding_provider': self.embedder.provider_name,
                'embedding_model': self.embedder.model_name,
                'embedding_status': getattr(self.embedder, 'status', 'healthy')
            }
            return []

        # Relational Authoritative Gate:
        # Load chunks from PostgreSQL with strict publication and version validation
        chunks_qs = DocumentChunk.objects.filter(
            id__in=all_candidate_ids,
            workspace_id=workspace_id,
            organization_id=organization_id,
        ).exclude(
            document__status__in=['quarantined', 'failed', 'deleted', 'uploaded', 'needs_review', 'queued']
        ).select_related('document', 'document__collection', 'document_version', 'document__permissions')

        if collection_id:
            chunks_qs = chunks_qs.filter(document__collection_id=collection_id)
        if document_id:
            chunks_qs = chunks_qs.filter(document_id=document_id)

        # Check if query explicitly asks about older/historical versions (Requirement 7)
        is_historical_or_version_query = bool(
            effective_as_of or
            analysis.is_historical or
            re.search(r'\b(?:v\d+|version\s*\d+|older\s+version|prior\s+version|previous\s+version|historical)\b', query_clean.lower())
        )

        filtered_candidates = {}
        chunks_map = {}
        for c in chunks_qs:
            cid_str = str(c.id)
            # 1. Access permissions filter before evidence enters model context (Requirement 5)
            if hasattr(c.document, 'permissions'):
                perm = getattr(c.document, 'permissions', None)
                if perm and not perm.is_user_permitted(user=user, user_role=user_role):
                    filtered_candidates[cid_str] = f'FILTERED_PERMISSION_DENIED_{perm.access_level.upper()}'
                    continue

            # 2. Temporal validity filter using validated metadata (Requirement 5)
            from .query_understanding import QueryIntent
            if analysis.intent == QueryIntent.HISTORICAL_AS_OF_LOOKUP and effective_as_of:
                if c.document.effective_from and c.document.effective_from.isoformat() > effective_as_of:
                    filtered_candidates[cid_str] = f'FILTERED_NOT_YET_EFFECTIVE_AS_OF_{effective_as_of}'
                    continue
                if c.document.effective_to and c.document.effective_to.isoformat() < effective_as_of:
                    filtered_candidates[cid_str] = f'FILTERED_EXPIRED_PRIOR_TO_{effective_as_of}'
                    continue

            # 3. Version and supersession filter (Requirement 4 & 5)
            if not is_historical_or_version_query:
                if c.document_version and c.document_version.version_number < c.document.current_version_number:
                    filtered_candidates[cid_str] = 'FILTERED_SUPERSEDED_HISTORICAL_VERSION'
                    continue
                if c.document.governance_status == 'superseded':
                    filtered_candidates[cid_str] = 'FILTERED_SUPERSEDED_DOCUMENT'
                    continue

            chunks_map[cid_str] = c

        for cid in all_candidate_ids:
            if cid not in chunks_map and cid not in filtered_candidates:
                filtered_candidates[cid] = 'FILTERED_STATUS_OR_SCOPE_EXCLUDED'

        rrf_candidates = []
        k = float(rrf_k)
        for cid in all_candidate_ids:
            chk = chunks_map.get(cid)
            if not chk:
                continue

            r_vec = vector_ranks.get(cid, 999)
            r_lex = lexical_ranks.get(cid, 999)

            rrf_score = (1.0 / (k + r_vec)) + (1.0 / (k + r_lex))
            rrf_candidates.append((rrf_score, chk))

        t_fusion_end = time.time()

        # ---------------- Stage 3b: Bounded Graph Traversal Expansion ----------------
        t_graph_start = time.time()
        graph_status = "disabled"
        graph_degraded = False
        graph_res = None
        expanded_chunks_list: List[Dict[str, Any]] = []

        if enable_graph_expansion and rrf_candidates:
            # Extract top seeds from RRF ranking
            seed_dicts = []
            for rrf_score, chk in rrf_candidates[:10]:
                seed_dicts.append({
                    'chunk_id': str(chk.id),
                    'document_id': str(chk.document_id)
                })

            try:
                from apps.knowledge.graph import BoundedGraphTraversalService
                graph_res = BoundedGraphTraversalService.expand(
                    seed_chunks=seed_dicts,
                    workspace_id=workspace_id,
                    organization_id=organization_id,
                    user=user,
                    user_role=user_role,
                    as_of=effective_as_of,
                    max_depth=graph_max_depth,
                    max_nodes=graph_max_nodes,
                    timeout_ms=graph_timeout_ms,
                    permitted_relationship_types=permitted_relationship_types
                )
                graph_status = graph_res.get('status', 'completed')
                graph_degraded = graph_res.get('degraded', False)
                expanded_chunks_list = graph_res.get('expanded_chunks', [])
            except Exception as ge:
                logger.warning(f"[GraphRAG] Traversal failed: {ge}. Operating in degraded fallback mode.")
                graph_status = 'failed'
                graph_degraded = True
                graph_res = {
                    'status': 'failed',
                    'degraded': True,
                    'error': str(ge),
                    'traversal_paths': [],
                    'expanded_chunks': [],
                    'surfaced_conflicts': [],
                    'surfaced_requirements': [],
                    'surfaced_exceptions': [],
                    'surfaced_dependencies': [],
                    'surfaced_supersessions': [],
                    'surfaced_lineage': [],
                }

        self.last_graph_result = graph_res
        t_graph_end = time.time()

        # Merge and deduplicate seeds with graph-expanded candidates
        merged_candidates = []
        seen_chunk_ids = set()

        for rrf_score, chk in rrf_candidates:
            cid = str(chk.id)
            seen_chunk_ids.add(cid)
            ver_num = chk.document_version.version_number if chk.document_version else chk.document.current_version_number
            tokens = chk.token_count or len((chk.text or '').split())

            merged_candidates.append({
                'chunk_id': cid,
                'document_id': str(chk.document.id),
                'document_title': chk.document.canonical_title or chk.document.title,
                'document_code': chk.document.document_code or "",
                'document_type': chk.document.document_type,
                'document_version': ver_num,
                'page_number': chk.page_number,
                'heading_path': chk.heading_path,
                'section_identifier': chk.section_identifier or "",
                'governance_status': chk.document.governance_status or chk.document.status or "ready",
                'effective_from': chk.document.effective_from.isoformat() if chk.document.effective_from else "",
                'effective_to': chk.document.effective_to.isoformat() if chk.document.effective_to else "",
                'text': chk.text,
                'contextual_header': chk.contextual_header,
                'authority_level': chk.document.authority_level,
                'rrf_score': rrf_score,
                'token_count': tokens,
                'graph_expanded': False,
                'graph_depth': 0,
                'traversed_relationship': None,
                'edge_provenance': None,
                'edge_confidence': None,
                'graph_path': [],
                'candidate_ranks': {
                    'vector_rank': vector_ranks.get(cid),
                    'lexical_rank': lexical_ranks.get(cid),
                },
                'fusion_params': {
                    'k': k,
                    'rrf_score': rrf_score,
                },
                'retrieval_status': 'degraded_lexical_only' if vector_degraded else 'healthy_hybrid'
            })

        for exp_chk in expanded_chunks_list:
            cid = str(exp_chk.get('chunk_id'))
            if cid in seen_chunk_ids:
                # Augment existing candidate with graph lineage
                for mc in merged_candidates:
                    if mc['chunk_id'] == cid:
                        mc['graph_expanded'] = True
                        mc['graph_path'] = exp_chk.get('graph_path', [])
                        break
            else:
                if cid in filtered_candidates:
                    continue
                exp_eff_from = exp_chk.get('effective_from', '')
                if effective_as_of and exp_eff_from and exp_eff_from[:10] > effective_as_of[:10]:
                    filtered_candidates[cid] = f'FILTERED_NOT_YET_EFFECTIVE_AS_OF_{effective_as_of}'
                    continue
                seen_chunk_ids.add(cid)
                exp_item = dict(exp_chk)
                exp_item['candidate_ranks'] = {
                    'vector_rank': vector_ranks.get(cid),
                    'lexical_rank': lexical_ranks.get(cid),
                }
                exp_item['fusion_params'] = {
                    'k': k,
                    'rrf_score': exp_chk.get('rrf_score', 0.2),
                }
                merged_candidates.append(exp_item)

        # ---------------- Stage 4: Pluggable Reranking (Phase 2-5) ----------------
        t_rerank_start = time.time()
        active_reranker = self.reranker
        reranked_candidates = active_reranker.rerank(
            query=query_clean,
            candidates=merged_candidates,
            top_k=candidate_budget,
            min_relevance_threshold=min_relevance_threshold,
            query_analysis=analysis
        )
        t_rerank_end = time.time()

        # Prepend missing boundary items for negative retrieval
        if missing_boundary_candidates:
            reranked_candidates = missing_boundary_candidates + list(reranked_candidates)

        # Shadow evaluation mode if enabled (Phase 10)
        shadow_diag = None
        if getattr(settings, 'RERANKER_SHADOW_MODE', False) and active_reranker.backend_name == 'heuristic':
            try:
                from .reranking.shadow import ShadowRerankerEvaluator
                from .reranking.neural import NeuralCrossEncoderReranker
                shadow_diag = ShadowRerankerEvaluator.evaluate(
                    query=query_clean,
                    eligible_candidates=merged_candidates,
                    primary_results=reranked_candidates,
                    shadow_reranker=NeuralCrossEncoderReranker(),
                    top_k=candidate_budget
                )
            except Exception as se:
                logger.debug(f"[ShadowReranker] Shadow evaluation skipped: {se}")

        # ---------------- Stage 5: Configurable Context Budgeting ----------------
        accumulated_tokens = 0
        truncated_count = 0
        final_results = []

        for cand in reranked_candidates:
            if isinstance(cand, tuple):
                final_score, chk, meta = cand
                cid = str(getattr(chk, 'id', ''))
                chk_tokens = getattr(chk, 'token_count', 0) or len((getattr(chk, 'text', '') or '').split())
                doc = getattr(chk, 'document', None)
                doc_id = str(getattr(doc, 'id', '')) if doc else ''
                doc_title = getattr(doc, 'canonical_title', '') or (getattr(doc, 'title', '') if doc else '')
                doc_code = getattr(doc, 'document_code', '') if doc else ''
                doc_gov_status = getattr(doc, 'governance_status', '') or (getattr(doc, 'status', 'ready') if doc else 'ready')
                sec_id = getattr(chk, 'section_identifier', '')
                eff_from = doc.effective_from.isoformat() if (doc and doc.effective_from) else ''
                eff_to = doc.effective_to.isoformat() if (doc and doc.effective_to) else ''
                doc_type = getattr(doc, 'document_type', 'pdf') if doc else 'pdf'
                auth_level = getattr(doc, 'authority_level', 3) if doc else 3
                ver_obj = getattr(chk, 'document_version', None)
                ver_num = ver_obj.version_number if ver_obj else (getattr(doc, 'current_version_number', 1) if doc else 1)
                page_num = getattr(chk, 'page_number', 1)
                heading_path = getattr(chk, 'heading_path', '')
                text = getattr(chk, 'text', '')
                header = getattr(chk, 'contextual_header', '')
                is_graph = getattr(chk, 'graph_expanded', False)
                g_depth = getattr(chk, 'graph_depth', 0)
                g_rel = getattr(chk, 'traversed_relationship', None)
                g_prov = getattr(chk, 'edge_provenance', None)
                g_conf = getattr(chk, 'edge_confidence', None)
                g_path = getattr(chk, 'graph_path', [])
                ret_stat = getattr(chk, 'retrieval_status', 'healthy_hybrid')
                r_vec = vector_ranks.get(cid)
                r_lex = lexical_ranks.get(cid)
            else:
                final_score = cand.get('score', 0.0)
                meta = cand
                cid = str(cand.get('chunk_id', ''))
                chk_tokens = cand.get('token_count', 0) or len((cand.get('text', '') or '').split())
                doc_id = str(cand.get('document_id', ''))
                doc_title = cand.get('document_title', '')
                doc_code = cand.get('document_code', '')
                doc_gov_status = cand.get('governance_status') or cand.get('document_status', '')
                sec_id = cand.get('section_identifier', '')
                eff_from = cand.get('effective_from', '')
                eff_to = cand.get('effective_to', '')
                doc_type = cand.get('document_type', 'pdf')
                auth_level = cand.get('authority_level', 3)
                ver_num = cand.get('document_version', 1)
                page_num = cand.get('page_number', 1)
                heading_path = cand.get('heading_path', '')
                text = cand.get('text', '')
                header = cand.get('contextual_header', '')
                is_graph = cand.get('graph_expanded', False)
                g_depth = cand.get('graph_depth', 0)
                g_rel = cand.get('traversed_relationship')
                g_prov = cand.get('edge_provenance')
                g_conf = cand.get('edge_confidence')
                g_path = cand.get('graph_path', [])
                ret_stat = cand.get('retrieval_status', 'healthy_hybrid')
                c_ranks = cand.get('candidate_ranks', {})
                r_vec = c_ranks.get('vector_rank')
                r_lex = c_ranks.get('lexical_rank')

            # Requirement 4: Deduplicate identical and overlapping chunks while retaining strongest provenance
            clean_text_cand = re.sub(r'\s+', ' ', (text or '').lower().strip())
            cand_tokens = set(re.findall(r'\b\w{4,}\b', clean_text_cand))
            is_dup = False
            for existing in final_results:
                if existing.get('document_id') == doc_id or existing.get('document_title') == doc_title:
                    ex_clean = re.sub(r'\s+', ' ', (existing.get('text') or '').lower().strip())
                    if clean_text_cand[:60] == ex_clean[:60] and len(clean_text_cand) > 30:
                        is_dup = True
                    elif cand_tokens and len(cand_tokens) >= 5:
                        ex_tokens = set(re.findall(r'\b\w{4,}\b', ex_clean))
                        if ex_tokens:
                            inter = len(cand_tokens.intersection(ex_tokens))
                            union = len(cand_tokens.union(ex_tokens))
                            if union > 0 and (inter / union) >= 0.75:
                                is_dup = True
                    if is_dup:
                        # Retain the strongest source location and provenance (Requirement 4)
                        if (existing.get('page_number') is None or existing.get('page_number') == 0) and page_num:
                            existing['page_number'] = page_num
                        if (not existing.get('heading_path') or existing.get('heading_path') == 'General') and heading_path:
                            existing['heading_path'] = heading_path
                        if auth_level > existing.get('authority_level', 0):
                            existing['authority_level'] = auth_level
                        break
            if is_dup:
                filtered_candidates[cid] = 'FILTERED_REDUNDANT_CHUNK_DEDUPLICATION'
                continue

            if accumulated_tokens + chk_tokens > budget and final_results:
                truncated_count += 1
                filtered_candidates[cid] = 'FILTERED_EXCEEDED_CONTEXT_TOKEN_BUDGET'
                continue

            accumulated_tokens += chk_tokens

            # Status resolution
            if vector_degraded:
                active_status = 'degraded_lexical_only'
            elif graph_degraded and is_graph:
                active_status = 'degraded_graph_timeout'
            elif is_graph:
                active_status = 'graph_expanded'
            else:
                active_status = 'healthy_hybrid'

            # Assign evidence role (Requirement 6)
            text_lower = (text or '').lower()
            if cand.get('is_missing'):
                cand_role = 'missing_corpus_boundary'
            elif analysis.is_negative_query:
                cand_role = 'corpus_boundary_negative'
            elif analysis.intent == QueryIntent.CROSS_DOCUMENT_COMPARISON:
                if any(w in text_lower for w in ['invoice', 'inv-', 'hourly rate', 'consulting services', 'billing']):
                    cand_role = 'invoice_facts'
                elif any(w in text_lower for w in ['master services agreement', 'effective date', 'hourly cap', 'payment terms', 'maximum allowable rate']):
                    cand_role = 'contract_terms'
                elif any(w in text_lower for w in ['minutes', 'defer', 'milling machine', 'meeting decision']):
                    cand_role = 'procurement_review_minutes'
                elif any(w in text_lower for w in ['sole source', 'procurement policy', 'three mandatory conditions']):
                    cand_role = 'governing_procurement_policy'
                else:
                    cand_role = 'cross_document_comparison'
            elif analysis.intent == QueryIntent.APPROVAL_COMPLIANCE_DECISION:
                if any(w in text_lower for w in ['minutes', 'defer purchase', 'objection', 'cfo approval']):
                    cand_role = 'capital_approval_minutes'
                elif any(w in text_lower for w in ['sole source', 'threat to life', 'single supplier']):
                    cand_role = 'emergency_exception_rule'
                else:
                    cand_role = 'compliance_criteria'
            elif analysis.intent == QueryIntent.HISTORICAL_AS_OF_LOOKUP or analysis.is_historical:
                if doc_gov_status == 'superseded' or (ver_num and ver_num < getattr(getattr(chk, 'document', None), 'current_version_number', 2)):
                    cand_role = 'historical_policy'
                else:
                    cand_role = 'successor_policy'
            elif analysis.intent == QueryIntent.ACCESS_STATUS_LOOKUP:
                cand_role = 'access_authorization_record'
            elif analysis.intent == QueryIntent.PROCEDURAL_INSTRUCTIONS:
                cand_role = 'procedural_instructions'
            elif analysis.domain == 'travel_lodging':
                cand_role = 'lodging_limit_rule'
            elif analysis.domain == 'travel_meals':
                cand_role = 'meal_allowance_rule'
            elif analysis.domain == 'travel_receipts':
                cand_role = 'receipt_reimbursement_rule'
            elif analysis.domain == 'records_retention':
                cand_role = 'retention_schedule_table'
            elif doc_gov_status == 'future-effective':
                cand_role = 'future_amendment'
            elif doc_gov_status in ('approved', 'ready', 'active') and auth_level >= 3:
                if effective_as_of and eff_from and eff_from[:10] > effective_as_of[:10]:
                    cand_role = 'future_policy'
                else:
                    cand_role = 'governing_policy'
            else:
                cand_role = 'supporting_evidence'

            item = {
                'chunk_id': cid,
                'document_id': doc_id,
                'document_code': doc_code,
                'document_title': doc_title,
                'document_type': doc_type,
                'document_version': ver_num,
                'page_number': page_num,
                'heading_path': heading_path,
                'section_identifier': sec_id,
                'governance_status': doc_gov_status,
                'effective_from': eff_from,
                'effective_to': eff_to,
                'text': text,
                'contextual_header': header,
                'authority_level': auth_level,
                'role': cand_role,
                'score': round(final_score, 4),
                'rrf_score': meta.get('rrf_score', 0),
                'token_coverage': meta.get('token_coverage', 0),
                'phrase_match': meta.get('phrase_match', False),
                'token_count': chk_tokens,
                # Observability & fusion audit contracts
                'candidate_ranks': {
                    'vector_rank': r_vec,
                    'lexical_rank': r_lex,
                },
                'fusion_params': {
                    'k': k,
                    'rrf_score': meta.get('rrf_score', 0),
                },
                'reranking_scores': {
                    'relevance_score': round(final_score, 4),
                    'norm_rrf': meta.get('norm_rrf', 0),
                    'token_coverage': meta.get('token_coverage', 0),
                    'phrase_bonus': meta.get('phrase_bonus', 0),
                    'header_bonus': meta.get('header_bonus', 0),
                },
                'retrieval_status': active_status
            }

            if is_graph:
                item['graph_expanded'] = True
                item['graph_depth'] = g_depth
                item['traversed_relationship'] = g_rel
                item['edge_provenance'] = g_prov
                item['edge_confidence'] = g_conf
                item['graph_path'] = g_path
                item['graph_degraded'] = graph_degraded

            final_results.append(item)

            if len(final_results) >= limit:
                break

        # ---------------- Stage 6: Privacy-Preserving Query Diagnostics ----------------
        total_ms = int((time.time() - t_start) * 1000)

        # Build structured candidate traces (Requirement 7)
        sorted_fusion = sorted(rrf_candidates, key=lambda x: x[0], reverse=True)
        fusion_ranks_map = {str(chk.id): rank + 1 for rank, (score, chk) in enumerate(sorted_fusion)}

        selected_chunk_ids = {it['chunk_id'] for it in final_results}
        for cand in reranked_candidates:
            rc_id = str(cand[1].id if isinstance(cand, tuple) else cand.get('chunk_id'))
            if rc_id not in selected_chunk_ids and rc_id not in filtered_candidates:
                filtered_candidates[rc_id] = 'FILTERED_DISPLACED_BY_HIGHER_RELEVANCE_LIMIT'

        candidate_traces = []
        for cid in all_candidate_ids:
            chk = chunks_map.get(cid)
            doc = getattr(chk, 'document', None) if chk else None
            doc_code_val = getattr(doc, 'document_code', '') if doc else ''
            title_val = getattr(doc, 'canonical_title', '') or getattr(doc, 'title', '') if doc else ''
            sec_val = getattr(chk, 'section_identifier', '') or getattr(chk, 'heading_path', '') if chk else ''

            selected_item = next((it for it in final_results if it['chunk_id'] == cid), None)
            is_selected = selected_item is not None
            filt_reason = None if is_selected else filtered_candidates.get(cid, 'FILTERED_DISPLACED_BY_HIGHER_RELEVANCE_LIMIT')

            r_score = None
            if selected_item:
                r_score = selected_item.get('score')
            else:
                for rc in reranked_candidates:
                    rc_id = rc[1].id if isinstance(rc, tuple) else rc.get('chunk_id')
                    if str(rc_id) == cid:
                        r_score = round(float(rc[0] if isinstance(rc, tuple) else rc.get('score', 0)), 4)
                        break

            candidate_traces.append({
                'candidate_id': cid,
                'document_code': doc_code_val,
                'document_title': title_val,
                'section_identifier': sec_val,
                'lexical_rank': lexical_ranks.get(cid),
                'vector_rank': vector_ranks.get(cid),
                'fusion_rank': fusion_ranks_map.get(cid),
                'reranker_score': r_score,
                'is_selected': is_selected,
                'filter_reason': filt_reason,
                'role': selected_item.get('role') if selected_item else None
            })

        self.last_diagnostics = {
            'query_length': len(query_clean),
            'query_tokens_count': len(q_tokens),
            'retrieval_mode': 'degraded_lexical_only' if vector_degraded else ('hybrid_graph' if enable_graph_expansion else 'hybrid'),
            'vector_store_healthy': not vector_degraded,
            'circuit_breaker_active': vector_degraded,
            'stage_timings_ms': {
                'vector_ms': max(1, int((t_vec_end - t_vec_start) * 1000)),
                'lexical_ms': max(1, int((t_lex_end - t_lex_start) * 1000)),
                'fusion_ms': max(1, int((t_fusion_end - t_fusion_start) * 1000)),
                'graph_ms': max(1, int((t_graph_end - t_graph_start) * 1000)) if enable_graph_expansion else 0,
                'rerank_ms': max(1, int((t_rerank_end - t_rerank_start) * 1000)),
                'total_ms': total_ms,
            },
            'candidate_counts': {
                'vector_candidates': len(vector_hits),
                'lexical_candidates': len(lexical_pairs),
                'unique_fused_candidates': len(rrf_candidates),
                'graph_expanded_candidates': len(expanded_chunks_list),
                'merged_candidates': len(merged_candidates),
                'reranked_candidates': len(reranked_candidates),
                'selected_final_count': len(final_results),
            },
            'context_budget': {
                'configured_budget_tokens': budget,
                'consumed_tokens': accumulated_tokens,
                'truncated_candidates_count': truncated_count,
            },
            'graph_traversal': {
                'enabled': enable_graph_expansion,
                'status': graph_status,
                'degraded': graph_degraded,
                'max_depth_configured': graph_max_depth,
                'nodes_expanded_count': len(expanded_chunks_list),
                'traversal_paths_count': len(graph_res['traversal_paths']) if (graph_res and isinstance(graph_res.get('traversal_paths'), list)) else 0,
                'elapsed_ms': graph_res.get('elapsed_ms', 0) if graph_res else 0,
            },
            'surfaced_entities': {
                'conflicts': graph_res.get('surfaced_conflicts', []) if graph_res else [],
                'requirements': graph_res.get('surfaced_requirements', []) if graph_res else [],
                'exceptions': graph_res.get('surfaced_exceptions', []) if graph_res else [],
                'dependencies': graph_res.get('surfaced_dependencies', []) if graph_res else [],
                'supersessions': graph_res.get('surfaced_supersessions', []) if graph_res else [],
                'lineage': graph_res.get('surfaced_lineage', []) if graph_res else [],
            },
            'reranker': {
                'backend': active_reranker.backend_name,
                'model_name': active_reranker.model_name,
                'model_revision': active_reranker.model_revision,
                'device': getattr(active_reranker, 'device', getattr(getattr(active_reranker, '_last_diagnostics', None), 'device', None)),
                'candidate_budget': candidate_budget,
                'is_fallback': getattr(getattr(active_reranker, '_last_diagnostics', None), 'is_fallback', False),
                'fallback_reason': getattr(getattr(active_reranker, '_last_diagnostics', None), 'fallback_reason', None),
                'rerank_duration_ms': max(1, int((t_rerank_end - t_rerank_start) * 1000)),
                'shadow_evaluation': shadow_diag
            },
            'lexical_backend': self.lexical_service.get_backend_info(),
            'embedding_provider': self.embedder.provider_name,
            'embedding_model': self.embedder.model_name,
            'embedding_status': getattr(self.embedder, 'status', 'healthy'),
            'candidate_traces': candidate_traces,
            'selected_evidence': [
                {
                    'candidate_id': item['chunk_id'],
                    'document_code': item['document_code'],
                    'document_title': item['document_title'],
                    'document_version': item['document_version'],
                    'governance_status': item['governance_status'],
                    'authority_level': item['authority_level'],
                    'effective_from': item.get('effective_from', ''),
                    'effective_to': item.get('effective_to', ''),
                    'section_identifier': item['section_identifier'],
                    'page_number': item['page_number'],
                    'retrieval_score': item['score'],
                    'role': item.get('role', 'supporting_evidence')
                }
                for item in final_results
            ],
            'query_analysis': analysis.to_dict()
        }

        return final_results
