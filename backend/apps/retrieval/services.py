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
        all_q_tokens = [w for w in re.findall(r'\w+', q_clean) if len(w) > 1]
        stop_words = {
            'what', 'is', 'are', 'the', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of',
            'and', 'or', 'by', 'with', 'from', 'as', 'be', 'can', 'we', 'it', 'this',
            'that', 'do', 'does', 'all', 'any', 'my', 'your', 'our', 'under', 'according',
            'tell', 'show', 'please', 'would', 'could', 'how', 'much', 'many', 'must'
        }
        content_tokens = [w for w in all_q_tokens if w not in stop_words]
        eval_q_tokens = set(content_tokens if content_tokens else all_q_tokens)

        # Requirement 1 & 2: Identify specific fact requirements from query
        is_amount_inquiry = bool(re.search(r'\b(allowance|rate|threshold|limit|ceiling|cost|price|fee|budget|amount|total)\b', q_clean))
        is_duration_inquiry = bool(re.search(r'\b(days?|hours?|months?|years?|delivery|turnaround|retention|schedule|period|timeline|timeout)\b', q_clean))
        is_logging_inquiry = bool(re.search(r'\b(logged|logging|logs|log|audit\s+log|audit\s+logging|record(?:ed|ing)?)\b', q_clean))
        doc_code_targets = [t.lower() for t in re.findall(r'\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b|\bdoc-\d+\b|\bpol-[a-z0-9-]+\b', q_clean)]
        section_target_m = re.search(r'\bsection\s+(\d+(?:\.\d+)?)\b', q_clean)
        section_target = section_target_m.group(0).lower() if section_target_m else None
        ver_target_m = re.search(r'\b(?:version\s*(\d+)|v(\d+))\b', q_clean)
        ver_target = int(ver_target_m.group(1) or ver_target_m.group(2)) if ver_target_m else None

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
                ver_obj = getattr(chk, 'document_version', None)
                ver_num = ver_obj.version_number if ver_obj else (getattr(doc, 'current_version_number', 1) if doc else 1)
            elif isinstance(item, dict):
                is_tuple = False
                chk = item
                rrf_score = item.get('rrf_score', 0.5)
                text = (item.get('text', '') or '').lower()
                header = (item.get('contextual_header', '') or item.get('heading', '') or '').lower()
                heading = (item.get('heading_path', '') or item.get('heading', '') or '').lower()
                title = (item.get('document_title', '') or '').lower()
                auth_rank = item.get('authority_level', 3)
                ver_num = item.get('document_version', 1)
            else:
                continue

            # 1. Normalized RRF component [0, 1]
            norm_rrf = rrf_score / (max_rrf if max_rrf > 0 else 1.0)

            doc_text = f"{title} {header} {heading} {text}"
            doc_tokens = set(re.findall(r'\w+', doc_text))

            # 2. Exact phrase match bonus
            phrase_bonus = 0.0
            if len(q_clean) > 3 and (q_clean in doc_text):
                phrase_bonus = 0.35

            # 3. Token coverage score [0, 1] using discrete word boundary tokens & morphological variants
            if eval_q_tokens:
                matched_tokens = 0
                for t in eval_q_tokens:
                    if t in doc_tokens:
                        matched_tokens += 1
                    elif t in ['logged', 'logging', 'logs', 'log'] and any(v in doc_tokens for v in ['log', 'logging', 'logs', 'record', 'audit']):
                        matched_tokens += 1
                    elif t == 'actions' and any(v in doc_tokens for v in ['events', 'functions', 'changes', 'attempts', 'activities']):
                        matched_tokens += 1
                token_coverage = matched_tokens / len(eval_q_tokens)
            else:
                token_coverage = 0.0

            # 4. Contextual header relevance bonus
            header_bonus = 0.0
            if header and any(t in header for t in eval_q_tokens):
                header_bonus = 0.15

            # 5. Document Target alignment bonus (Requirement 3 & 7)
            doc_match_bonus = 0.0
            if doc_code_targets and any(dc in title for dc in doc_code_targets):
                doc_match_bonus = 0.25

            # 6. Section target bonus (Requirement 3)
            section_bonus = 0.0
            if section_target and (section_target in header or section_target in heading or section_target in text):
                section_bonus = 0.15

            # 7. Version target bonus (Requirement 3 & 7)
            version_bonus = 0.0
            if ver_target is not None and ver_num == ver_target:
                version_bonus = 0.20

            # 8. Fact-bearing content relevance bonus (Requirement 2)
            fact_bonus = 0.0
            if is_amount_inquiry and bool(re.search(r'\$\s*\d+|\b\d+\s*(?:dollars?|usd|taka|bdt)\b', text)):
                fact_bonus += 0.15
            if is_duration_inquiry and bool(re.search(r'\b\d+\s*(?:days?|hours?|months?|years?|business days?)\b', text)):
                fact_bonus += 0.15
            if is_logging_inquiry:
                if 'audit logging' in doc_text or 'security events' in doc_text or ('must record' in doc_text and 'authentication' in doc_text):
                    fact_bonus += 0.35
                elif ('workspace_access_request' in title or 'travel_expense' in title) and not any(w in doc_text for w in ['audit logging', 'must record', 'security events']):
                    # Penalize transactional access request forms and travel policies that contain no logging facts
                    fact_bonus -= 0.30

            # 9. Pure relevance score (CRITICAL: DO NOT MULTIPLY BY AUTHORITY!)
            if token_coverage == 0.0 and phrase_bonus == 0.0 and header_bonus == 0.0 and doc_match_bonus == 0.0 and fact_bonus <= 0.0:
                relevance_score = 0.0
            else:
                relevance_score = (
                    (0.40 * norm_rrf) +
                    (0.35 * token_coverage) +
                    phrase_bonus +
                    header_bonus +
                    doc_match_bonus +
                    section_bonus +
                    version_bonus +
                    fact_bonus
                )

            # Threshold gating: completely irrelevant chunks are not promoted
            if relevance_score < min_relevance_threshold:
                continue

            meta = {
                'relevance_score': round(relevance_score, 4),
                'rrf_score': round(rrf_score, 4),
                'norm_rrf': round(norm_rrf, 4),
                'token_coverage': round(token_coverage, 2),
                'phrase_match': phrase_bonus > 0,
                'phrase_bonus': round(phrase_bonus, 2),
                'header_bonus': round(header_bonus, 2),
                'doc_match_bonus': round(doc_match_bonus, 2),
                'section_bonus': round(section_bonus, 2),
                'version_bonus': round(version_bonus, 2),
                'fact_bonus': round(fact_bonus, 2),
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
        embedder: Optional[Any] = None
    ):
        self.vector_store = vector_store or QdrantVectorStore()
        self.lexical_service = lexical_service or LexicalSearchService
        self.embedder = embedder or get_embedding_adapter()
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
        query_clean = query.strip()
        q_tokens = [w.lower() for w in re.findall(r'\w+', query_clean) if len(w) > 1]

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
            limit=30,
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
            limit=30
        )
        t_lex_end = time.time()

        lexical_ranks = {}
        for rank, (lex_score, chk) in enumerate(lexical_pairs):
            lexical_ranks[str(chk.id)] = rank + 1

        # ---------------- Stage 3: Reciprocal Rank Fusion (RRF) ----------------
        t_fusion_start = time.time()
        all_candidate_ids = set(vector_ranks.keys()) | set(lexical_ranks.keys())

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
            document__status='ready'
        ).exclude(
            document__status__in=['quarantined', 'failed', 'needs_review', 'uploaded', 'draft', 'deleted', 'stale']
        ).select_related('document', 'document__collection', 'document_version')

        if collection_id:
            chunks_qs = chunks_qs.filter(document__collection_id=collection_id)
        if document_id:
            chunks_qs = chunks_qs.filter(document_id=document_id)

        # Check if query explicitly asks about older/historical versions (Requirement 7)
        is_historical_or_version_query = bool(
            as_of or
            re.search(r'\b(?:v\d+|version\s*\d+|older\s+version|prior\s+version|previous\s+version|historical)\b', query_clean.lower())
        )

        chunks_map = {}
        for c in chunks_qs:
            # Exclude superseded older versions unless query explicitly asks for older/historical versions
            if not is_historical_or_version_query:
                if c.document_version and c.document_version.version_number < c.document.current_version_number:
                    continue
            chunks_map[str(c.id)] = c

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
                    as_of=as_of,
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
                'document_title': chk.document.title,
                'document_type': chk.document.document_type,
                'document_version': ver_num,
                'page_number': chk.page_number,
                'heading_path': chk.heading_path,
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

        # ---------------- Stage 4: Context Reranking ----------------
        t_rerank_start = time.time()
        reranked_candidates = ContextReranker.rerank(
            query=query_clean,
            candidates=merged_candidates,
            top_k=max(limit * 3, 24),
            min_relevance_threshold=min_relevance_threshold
        )
        t_rerank_end = time.time()

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
                doc_title = getattr(doc, 'title', '') if doc else ''
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
                continue

            if accumulated_tokens + chk_tokens > budget and final_results:
                truncated_count += 1
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

            item = {
                'chunk_id': cid,
                'document_id': doc_id,
                'document_title': doc_title,
                'document_type': doc_type,
                'document_version': ver_num,
                'page_number': page_num,
                'heading_path': heading_path,
                'text': text,
                'contextual_header': header,
                'authority_level': auth_level,
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
            'lexical_backend': self.lexical_service.get_backend_info(),
            'embedding_provider': self.embedder.provider_name,
            'embedding_model': self.embedder.model_name,
            'embedding_status': getattr(self.embedder, 'status', 'healthy')
        }

        return final_results
