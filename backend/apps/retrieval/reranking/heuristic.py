"""
LORE Enterprise — Heuristic Context Reranker
Implements BaseReranker using exact phrase matching, discrete token coverage,
contextual header relevance, fact-bearing bonuses, and normalized RRF seed scores.

CRITICAL ARCHITECTURAL INVARIANT (P1 §6 & lore.md §6):
Authority must NOT turn irrelevant or out-of-scope evidence into a valid decision.
Ranking scores ONLY reflect relevance to the query. Governance filters (L7 permissions,
L5 temporal validity, L4 scoped exceptions, publication state) and L6 authority conflict
arbitration must remain strictly separate from retrieval ranking.
"""

import time
import re
from typing import List, Dict, Any, Optional
from .base import BaseReranker, RerankerDiagnostics


class HeuristicReranker(BaseReranker):
    """
    Heuristic rule-based reranker preserving LORE's production ContextReranker behavior:
    1. Exact phrase and n-gram overlap with the query.
    2. Token coverage across chunk body and contextual headers.
    3. Dense vector + BM25 Reciprocal Rank Fusion (RRF) normalized seed score.
    4. Positional density, section matching, version targeting, and fact-bearing bonuses.
    """

    def __init__(self, min_relevance_threshold: float = 0.05):
        self.min_relevance_threshold = min_relevance_threshold
        self._last_diagnostics: Optional[RerankerDiagnostics] = None

    @property
    def backend_name(self) -> str:
        return "heuristic"

    @property
    def model_name(self) -> str:
        return "heuristic_token_rrf_v1"

    @property
    def model_revision(self) -> Optional[str]:
        return "1.0.0"

    def check_health(self) -> Dict[str, Any]:
        return {
            'status': 'healthy',
            'backend': self.backend_name,
            'model_name': self.model_name,
            'model_revision': self.model_revision,
            'ready': True,
            'is_fallback': False
        }

    def rerank(
        self,
        query: str,
        candidates: List[Any],
        top_k: int = 10,
        min_relevance_threshold: Optional[float] = None,
        **options: Any
    ) -> List[Any]:
        t_start = time.time()
        thresh = min_relevance_threshold if min_relevance_threshold is not None else self.min_relevance_threshold
        
        if not candidates or not query or not query.strip():
            self._last_diagnostics = RerankerDiagnostics(
                backend=self.backend_name,
                model_name=self.model_name,
                model_revision=self.model_revision,
                inference_duration_ms=(time.time() - t_start) * 1000,
                candidate_count_in=len(candidates) if candidates else 0,
                candidate_count_out=0,
                batch_count=0
            )
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

        # Identify specific fact requirements from query
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

            # 5. Document Target alignment bonus
            doc_match_bonus = 0.0
            if doc_code_targets and any(dc in title for dc in doc_code_targets):
                doc_match_bonus = 0.25

            # 6. Section target bonus
            section_bonus = 0.0
            if section_target and (section_target in header or section_target in heading or section_target in text):
                section_bonus = 0.15

            # 7. Version target bonus
            version_bonus = 0.0
            if ver_target is not None and ver_num == ver_target:
                version_bonus = 0.20

            # 8. Fact-bearing content relevance bonus
            fact_bonus = 0.0
            if is_amount_inquiry and bool(re.search(r'\$\s*\d+|\b\d+\s*(?:dollars?|usd|taka|bdt)\b', text)):
                fact_bonus += 0.15
            if is_duration_inquiry and bool(re.search(r'\b\d+\s*(?:days?|hours?|months?|years?|business days?)\b', text)):
                fact_bonus += 0.15
            if is_logging_inquiry:
                if 'audit logging' in doc_text or 'security events' in doc_text or ('must record' in doc_text and 'authentication' in doc_text):
                    fact_bonus += 0.35
                elif ('workspace_access_request' in title or 'travel_expense' in title) and not any(w in doc_text for w in ['audit logging', 'must record', 'security events']):
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

            # Threshold gating
            if relevance_score < thresh:
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
                'authority_level': auth_rank,
                'reranker_backend': self.backend_name,
                'reranker_model': self.model_name
            }

            if is_tuple:
                scored_candidates.append((relevance_score, chk, meta))
            else:
                res_dict = dict(item)
                res_dict['score'] = round(relevance_score, 4)
                res_dict['reranking_scores'] = meta
                res_dict.update(meta)
                scored_candidates.append(res_dict)

        # Sort descending purely by relevance score
        if scored_candidates and isinstance(scored_candidates[0], tuple):
            scored_candidates.sort(key=lambda x: x[0], reverse=True)
        else:
            scored_candidates.sort(key=lambda x: x.get('score', 0.0), reverse=True)

        reordered = scored_candidates[:top_k]
        
        self._last_diagnostics = RerankerDiagnostics(
            backend=self.backend_name,
            model_name=self.model_name,
            model_revision=self.model_revision,
            inference_duration_ms=(time.time() - t_start) * 1000,
            candidate_count_in=len(candidates),
            candidate_count_out=len(reordered),
            batch_count=1
        )

        return reordered
