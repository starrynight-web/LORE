"""
LORE Enterprise — Reranker Factory & Fallback Management
Manages dependency injection, settings resolution, model initialization,
and transparent fallback policies between neural and heuristic backends.
"""

import logging
from typing import Optional, Dict, Any, List
from django.conf import settings

from .base import (
    BaseReranker,
    RerankerBackend,
    FallbackPolicy,
    RerankerDiagnostics,
    ModelUnavailableError,
    RerankingTimeoutError
)
from .heuristic import HeuristicReranker
from .neural import NeuralCrossEncoderReranker

logger = logging.getLogger(__name__)


class ResilientFallbackReranker(BaseReranker):
    """
    Reranker wrapper that attempts primary reranker (e.g. neural)
    and falls back to heuristic reranking upon model or inference failure.
    Accurately records fallback status and reason in diagnostics.
    """

    def __init__(
        self,
        primary_reranker: BaseReranker,
        fallback_policy: FallbackPolicy = FallbackPolicy.HEURISTIC,
        fallback_reranker: Optional[BaseReranker] = None
    ):
        self.primary = primary_reranker
        self.fallback_policy = fallback_policy
        self.fallback = fallback_reranker or HeuristicReranker()
        self._last_diagnostics: Optional[RerankerDiagnostics] = None

    @property
    def backend_name(self) -> str:
        if self._last_diagnostics and self._last_diagnostics.is_fallback:
            return f"{self.fallback.backend_name} (fallback from {self.primary.backend_name})"
        return self.primary.backend_name

    @property
    def model_name(self) -> str:
        if self._last_diagnostics and self._last_diagnostics.is_fallback:
            return self.fallback.model_name
        return self.primary.model_name

    @property
    def model_revision(self) -> Optional[str]:
        if self._last_diagnostics and self._last_diagnostics.is_fallback:
            return self.fallback.model_revision
        return self.primary.model_revision

    def check_health(self) -> Dict[str, Any]:
        p_health = self.primary.check_health()
        f_health = self.fallback.check_health()
        return {
            'primary': p_health,
            'fallback_policy': self.fallback_policy.value,
            'fallback_available': f_health.get('ready', True),
            'status': p_health.get('status', 'healthy')
        }

    def rerank(
        self,
        query: str,
        candidates: List[Any],
        top_k: int = 10,
        min_relevance_threshold: Optional[float] = None,
        **options: Any
    ) -> List[Any]:
        try:
            results = self.primary.rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
                min_relevance_threshold=min_relevance_threshold,
                **options
            )
            # Inherit diagnostics from primary
            if hasattr(self.primary, '_last_diagnostics'):
                self._last_diagnostics = getattr(self.primary, '_last_diagnostics')
            return results

        except (ModelUnavailableError, RerankingTimeoutError, Exception) as exc:
            logger.warning(
                f"[RerankerFallback] Primary reranker '{self.primary.model_name}' failed: {exc}. "
                f"Policy: {self.fallback_policy.value}"
            )
            if self.fallback_policy == FallbackPolicy.FAIL:
                raise

            # Execute Heuristic Fallback
            results = self.fallback.rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
                min_relevance_threshold=min_relevance_threshold,
                **options
            )
            diag = getattr(self.fallback, '_last_diagnostics', None)
            if diag:
                self._last_diagnostics = RerankerDiagnostics(
                    backend=self.fallback.backend_name,
                    model_name=self.fallback.model_name,
                    model_revision=self.fallback.model_revision,
                    device=None,
                    inference_duration_ms=diag.inference_duration_ms,
                    candidate_count_in=diag.candidate_count_in,
                    candidate_count_out=diag.candidate_count_out,
                    batch_count=diag.batch_count,
                    is_fallback=True,
                    fallback_reason=f"{type(exc).__name__}: {str(exc)}"
                )
            return results


class RerankerFactory:
    """Factory for selecting and configuring rerankers based on settings."""

    @classmethod
    def get_candidate_budget(cls, limit: int = 8) -> int:
        """
        Computes the candidate retrieval budget before reranking.
        budget = min(RERANKER_MAX_CANDIDATES, max(RERANKER_CANDIDATE_FLOOR, limit * RERANKER_CANDIDATE_MULTIPLIER))
        """
        multiplier = int(getattr(settings, 'RERANKER_CANDIDATE_MULTIPLIER', 3))
        floor = int(getattr(settings, 'RERANKER_CANDIDATE_FLOOR', 24))
        max_candidates = int(getattr(settings, 'RERANKER_MAX_CANDIDATES', 100))

        computed = max(floor, limit * multiplier)
        return min(max_candidates, computed)

    @classmethod
    def get_reranker(
        cls,
        backend: Optional[str] = None,
        fallback_policy: Optional[str] = None,
        model_name: Optional[str] = None,
        model_revision: Optional[str] = None,
        device: Optional[str] = None,
        batch_size: Optional[int] = None,
        max_length: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        min_relevance_threshold: Optional[float] = None,
        engine_override: Optional[Any] = None
    ) -> BaseReranker:
        """
        Creates and returns the configured reranker instance.
        """
        raw_backend = backend or getattr(settings, 'RERANKER_BACKEND', 'heuristic')
        selected_backend = RerankerBackend(str(raw_backend).lower())

        raw_fallback = fallback_policy or getattr(settings, 'RERANKER_FALLBACK', 'heuristic')
        selected_fallback = FallbackPolicy(str(raw_fallback).lower())

        threshold = min_relevance_threshold if min_relevance_threshold is not None else float(getattr(settings, 'RERANKER_MIN_RELEVANCE', 0.05))

        if selected_backend == RerankerBackend.HEURISTIC:
            return HeuristicReranker(min_relevance_threshold=threshold)

        # Neural Cross-Encoder Reranker
        model = model_name or getattr(settings, 'RERANKER_MODEL', 'BAAI/bge-reranker-v2-m3')
        revision = model_revision or getattr(settings, 'RERANKER_MODEL_REVISION', 'main')
        dev = device or getattr(settings, 'RERANKER_DEVICE', None)
        bs = batch_size or int(getattr(settings, 'RERANKER_BATCH_SIZE', 16))
        ml = max_length or int(getattr(settings, 'RERANKER_MAX_LENGTH', 512))
        timeout = timeout_seconds or float(getattr(settings, 'RERANKER_TIMEOUT_SECONDS', 5.0))

        primary_neural = NeuralCrossEncoderReranker(
            model_name_or_path=model,
            model_revision=revision,
            device=dev,
            batch_size=bs,
            max_length=ml,
            timeout_seconds=timeout,
            min_relevance_threshold=threshold,
            engine_override=engine_override
        )

        return ResilientFallbackReranker(
            primary_reranker=primary_neural,
            fallback_policy=selected_fallback,
            fallback_reranker=HeuristicReranker(min_relevance_threshold=threshold)
        )
