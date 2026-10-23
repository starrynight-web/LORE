import time
import logging
import threading
from enum import Enum
from typing import Callable, Any, Optional, Dict, List

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "CLOSED"       # Normal operation; requests pass through
    OPEN = "OPEN"           # Tripped; requests immediately fall back or fail
    HALF_OPEN = "HALF_OPEN" # Probing recovery with limited canary requests

class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""
    pass

class CircuitBreaker:
    """
    Enterprise Circuit Breaker for external dependencies (Qdrant vector store, Groq LLM API).
    Specification: Master Prompt P3 §19 (Operational Resilience & Circuit Breakers).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        expected_exceptions: Optional[tuple] = None
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions or (Exception,)

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._lock = threading.RLock()

        # Telemetry metrics
        self.total_calls = 0
        self.total_successes = 0
        self.total_failures = 0
        self.total_fallbacks = 0

    def call(self, func: Callable, *args, fallback: Optional[Callable] = None, **kwargs) -> Any:
        with self._lock:
            self.total_calls += 1
            current_time = time.time()

            # Check if OPEN state has expired and should transition to HALF_OPEN
            if self.state == CircuitState.OPEN:
                if (current_time - self.last_failure_time) >= self.recovery_timeout:
                    logger.info(f"[CircuitBreaker:{self.name}] Recovery timeout reached. Transitioning to HALF_OPEN.")
                    self.state = CircuitState.HALF_OPEN
                else:
                    self.total_fallbacks += 1
                    if fallback is not None:
                        logger.warning(f"[CircuitBreaker:{self.name}] Circuit is OPEN. Invoking fallback.")
                        return fallback(*args, **kwargs)
                    raise CircuitBreakerOpenException(f"Circuit breaker '{self.name}' is OPEN. Operation aborted.")

        # Attempt the primary function call
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exceptions as exc:
            self._on_failure(exc)
            if fallback is not None:
                with self._lock:
                    self.total_fallbacks += 1
                logger.warning(f"[CircuitBreaker:{self.name}] Call failed ({exc}). Invoking fallback.")
                return fallback(*args, **kwargs)
            raise

    def _on_success(self):
        with self._lock:
            self.total_successes += 1
            if self.state == CircuitState.HALF_OPEN:
                logger.info(f"[CircuitBreaker:{self.name}] Probe succeeded. Transitioning from HALF_OPEN to CLOSED.")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def _on_failure(self, exc: Exception):
        with self._lock:
            self.total_failures += 1
            self.last_failure_time = time.time()
            self.failure_count += 1
            logger.warning(f"[CircuitBreaker:{self.name}] Failure #{self.failure_count}: {exc}")

            if self.failure_count >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.error(f"[CircuitBreaker:{self.name}] Failure threshold ({self.failure_threshold}) reached! Tripping circuit to OPEN.")
                    self.state = CircuitState.OPEN

    def reset(self):
        """Manually resets the circuit breaker to CLOSED."""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.last_failure_time = 0.0

    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'name': self.name,
                'state': self.state.value,
                'failure_count': self.failure_count,
                'failure_threshold': self.failure_threshold,
                'recovery_timeout': self.recovery_timeout,
                'total_calls': self.total_calls,
                'total_successes': self.total_successes,
                'total_failures': self.total_failures,
                'total_fallbacks': self.total_fallbacks,
                'is_healthy': self.state == CircuitState.CLOSED
            }

# Process-wide circuit breakers
qdrant_circuit_breaker = CircuitBreaker("qdrant_vector_store", failure_threshold=3, recovery_timeout=30.0)
llm_circuit_breaker = CircuitBreaker("llm_inference", failure_threshold=3, recovery_timeout=30.0)

def resilient_vector_search(
    vector_store,
    collection_name: str,
    query_vector: List[float],
    filter_dict: Optional[Dict[str, Any]] = None,
    limit: int = 10,
    workspace_id: Optional[str] = None,
    query_text: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Executes vector search wrapped in the Qdrant circuit breaker.
    If Qdrant fails or circuit is open, gracefully falls back to PostgreSQL chunk search.
    """
    def _execute_primary():
        return vector_store.search(
            collection_name=collection_name,
            query_vector=query_vector,
            filter_dict=filter_dict,
            limit=limit
        )

    def _execute_fallback():
        """Fallback: Query database lexically via LexicalSearchService with strict publication filtering."""
        from apps.knowledge.models import DocumentChunk
        from apps.retrieval.lexical import LexicalSearchService

        logger.warning(
            f"[Qdrant Outage Fallback] Executing structured lexical fallback for workspace={workspace_id}, query='{query_text}'"
        )

        org_id = filter_dict.get('organization_id') if filter_dict else ""
        ws_id = workspace_id or (filter_dict.get('workspace_id') if filter_dict else "")
        col_id = filter_dict.get('collection_id') if filter_dict else None
        doc_id = filter_dict.get('document_id') if filter_dict else None

        lex_pairs = LexicalSearchService.search_chunks(
            query=query_text or "",
            workspace_id=str(ws_id) if ws_id else "",
            organization_id=str(org_id) if org_id else "",
            collection_id=col_id,
            document_id=doc_id,
            limit=limit
        )

        fallback_results = []
        for rank, (score, c) in enumerate(lex_pairs):
            # Guard against superseded versions
            if c.document_version and c.document_version.version_number < c.document.current_version_number:
                continue

            fallback_results.append({
                'id': str(c.id),
                'score': score,
                'payload': {
                    'chunk_id': str(c.id),
                    'document_id': str(c.document_id),
                    'document_version': c.document_version.version_number if c.document_version else c.document.current_version_number,
                    'document_title': c.document.title,
                    'organization_id': str(c.organization_id),
                    'workspace_id': str(c.workspace_id),
                    'collection_id': str(c.document.collection_id) if c.document.collection_id else "",
                    'page_number': c.page_number,
                    'heading_path': c.heading_path,
                    'authority_level': c.document.authority_level,
                    'text': c.text[:300],
                    'fallback_mode': 'lexical_only',
                    'circuit_breaker_active': True,
                    'retrieval_status': 'degraded_lexical_only'
                }
            })
        return fallback_results

    return qdrant_circuit_breaker.call(_execute_primary, fallback=_execute_fallback)
