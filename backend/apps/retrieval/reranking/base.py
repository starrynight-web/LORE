"""
LORE Enterprise — Pluggable Reranker Interface & Data Contracts
Defines the common protocol, data structures, and diagnostic contracts for all rerankers.
Preserves candidate identity, original metadata, document IDs, chunk IDs, source locators,
provenance, permissions, and citation identifiers across all reranking stages.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Union


class RerankerBackend(str, Enum):
    """Supported reranker backends."""
    HEURISTIC = "heuristic"
    NEURAL = "neural"


class FallbackPolicy(str, Enum):
    """Fallback policies when the primary reranker fails or is unavailable."""
    HEURISTIC = "heuristic"
    FAIL = "fail"


class RerankerException(Exception):
    """Base exception for reranking errors."""
    pass


class ModelUnavailableError(RerankerException):
    """Raised when a neural reranker model cannot be loaded or initialized."""
    pass


class RerankingTimeoutError(RerankerException):
    """Raised when reranking inference exceeds the configured timeout budget."""
    pass


@dataclass
class RerankerDiagnostics:
    """Diagnostic telemetry captured during reranking."""
    backend: str
    model_name: str
    model_revision: Optional[str] = None
    device: Optional[str] = None
    inference_duration_ms: float = 0.0
    candidate_count_in: int = 0
    candidate_count_out: int = 0
    batch_count: int = 0
    is_fallback: bool = False
    fallback_reason: Optional[str] = None
    batch_size: int = 16
    max_length: int = 512

    def to_dict(self) -> Dict[str, Any]:
        return {
            'backend': self.backend,
            'model_name': self.model_name,
            'model_revision': self.model_revision,
            'device': self.device,
            'inference_duration_ms': round(self.inference_duration_ms, 2),
            'candidate_count_in': self.candidate_count_in,
            'candidate_count_out': self.candidate_count_out,
            'batch_count': self.batch_count,
            'is_fallback': self.is_fallback,
            'fallback_reason': self.fallback_reason,
            'batch_size': self.batch_size,
            'max_length': self.max_length,
        }


@dataclass
class RerankResult:
    """Typed result returned by a reranker implementation."""
    candidates: List[Any]
    reranker_id: str
    reranker_version: str
    is_fallback: bool = False
    fallback_reason: Optional[str] = None
    diagnostics: Optional[RerankerDiagnostics] = None


class BaseReranker(ABC):
    """
    Common interface for all LORE rerankers (heuristic, neural, and hybrid).
    
    Guarantees:
    1. Preserves candidate identity, document IDs, chunk IDs, citations, provenance, and permissions.
    2. Scores query-candidate pairs strictly on relevance without confusing relevance with authority.
    3. Emits structured diagnostics without leaking protected document contents or secrets.
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: List[Any],
        top_k: int = 10,
        min_relevance_threshold: Optional[float] = None,
        **options: Any
    ) -> List[Any]:
        """
        Reorders candidates descending by query-document relevance.
        
        Args:
            query: The user query string.
            candidates: Ordered collection of candidate evidence chunks (tuples or dicts).
            top_k: Maximum number of reordered candidates to return.
            min_relevance_threshold: Minimum score threshold for candidate inclusion.
            **options: Additional backend-specific options.
            
        Returns:
            Reordered list of candidate records with attached relevance scores and metadata.
        """
        pass

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Returns health, readiness, and device diagnostics without leaking credentials or paths."""
        pass

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Identifier of the reranker backend (e.g. 'heuristic', 'neural')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier or heuristic algorithm name."""
        pass

    @property
    @abstractmethod
    def model_revision(self) -> Optional[str]:
        """Pinned model revision or version identifier."""
        pass
