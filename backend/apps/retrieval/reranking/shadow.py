"""
LORE Enterprise — Shadow Mode Reranker Evaluator
Runs candidate neural cross-encoder in shadow evaluation mode over identical eligible candidate sets
without affecting production answers, without leaking protected document contents, and without
side effects.
"""

import time
import logging
from typing import List, Dict, Any, Optional
from .base import BaseReranker

logger = logging.getLogger(__name__)


class ShadowRerankerEvaluator:
    """
    Executes shadow reranking comparisons between primary and experimental backends.
    """

    @classmethod
    def evaluate(
        cls,
        query: str,
        eligible_candidates: List[Any],
        primary_results: List[Any],
        shadow_reranker: BaseReranker,
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Runs shadow reranker on eligible candidates and returns privacy-safe comparison diagnostics.
        """
        t0 = time.time()
        shadow_error = None
        shadow_results = []

        try:
            shadow_results = shadow_reranker.rerank(
                query=query,
                candidates=eligible_candidates,
                top_k=top_k
            )
        except Exception as e:
            shadow_error = str(e)
            logger.warning(f"[ShadowReranker] Shadow evaluation execution failed: {e}")

        shadow_duration_ms = (time.time() - t0) * 1000

        # Extract top IDs for agreement comparison
        def _get_cid(item):
            if isinstance(item, tuple):
                return str(getattr(item[1], 'id', ''))
            elif isinstance(item, dict):
                return str(item.get('chunk_id', ''))
            return ''

        primary_ids = [_get_cid(c) for c in primary_results[:top_k] if _get_cid(c)]
        shadow_ids = [_get_cid(c) for c in shadow_results[:top_k] if _get_cid(c)]

        top1_match = bool(primary_ids and shadow_ids and primary_ids[0] == shadow_ids[0])
        overlap_count = len(set(primary_ids).intersection(set(shadow_ids)))
        jaccard = (overlap_count / len(set(primary_ids).union(set(shadow_ids)))) if (primary_ids or shadow_ids) else 1.0

        return {
            'shadow_enabled': True,
            'shadow_backend': shadow_reranker.backend_name,
            'shadow_model': shadow_reranker.model_name,
            'shadow_duration_ms': round(shadow_duration_ms, 2),
            'shadow_error': shadow_error,
            'agreement': {
                'top1_match': top1_match,
                'top_k_overlap': overlap_count,
                'jaccard_similarity': round(jaccard, 3),
            }
        }
