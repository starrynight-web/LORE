"""
LORE Enterprise — Reranking Package
Exposes pluggable rerankers, interfaces, and factory methods.
"""

from .base import (
    BaseReranker,
    RerankerBackend,
    FallbackPolicy,
    RerankerDiagnostics,
    RerankResult,
    RerankerException,
    ModelUnavailableError,
    RerankingTimeoutError,
)
from .heuristic import HeuristicReranker
from .neural import NeuralCrossEncoderReranker
from .shadow import ShadowRerankerEvaluator
from .factory import RerankerFactory, ResilientFallbackReranker

__all__ = [
    'BaseReranker',
    'RerankerBackend',
    'FallbackPolicy',
    'RerankerDiagnostics',
    'RerankResult',
    'RerankerException',
    'ModelUnavailableError',
    'RerankingTimeoutError',
    'HeuristicReranker',
    'NeuralCrossEncoderReranker',
    'ShadowRerankerEvaluator',
    'RerankerFactory',
    'ResilientFallbackReranker',
]
