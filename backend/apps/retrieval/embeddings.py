import math
import hashlib
import logging
from typing import List, Optional, Dict, Any
from django.conf import settings

logger = logging.getLogger(__name__)

class EmbeddingConfigurationError(RuntimeError):
    """Raised when an embedding provider fails to initialize and silent fallback is disabled."""
    pass


class BaseEmbeddingAdapter:
    """Abstract interface for LORE Enterprise embedding adapters."""
    dimension: int = 384
    provider_name: str = "base"
    model_name: str = "base"
    is_fallback: bool = False
    status: str = "healthy"

    def embed_text(self, text: str) -> List[float]:
        raise NotImplementedError

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class SentenceTransformerEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    Production-grade local semantic embedding adapter using SentenceTransformers.
    Zero paid API requirement, fast GPU/CPU vector encoding, 384-dimensional dense vectors.
    """
    dimension = 384
    provider_name = "sentence-transformers"
    model_name = "all-MiniLM-L6-v2"
    is_fallback = False
    status = "healthy"
    _model_instance = None

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or getattr(settings, 'EMBEDDING_MODEL_NAME', 'all-MiniLM-L6-v2')
        self._load_model()

    def _load_model(self):
        if SentenceTransformerEmbeddingAdapter._model_instance is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading SentenceTransformer embedding model: {self.model_name}")
                SentenceTransformerEmbeddingAdapter._model_instance = SentenceTransformer(self.model_name)
            except Exception as e:
                logger.error(f"Failed to load SentenceTransformer ({self.model_name}): {e}")
                raise e

    @property
    def model(self) -> Any:
        if SentenceTransformerEmbeddingAdapter._model_instance is None:
            self._load_model()
        instance = SentenceTransformerEmbeddingAdapter._model_instance
        if instance is None:
            raise RuntimeError("SentenceTransformer model could not be initialized")
        return instance

    def embed_text(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * self.dimension
        try:
            vec = self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.warning(f"Error encoding text with SentenceTransformer: {e}")
            return [0.0] * self.dimension

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            vecs = self.model.encode(texts, batch_size=32, convert_to_numpy=True, normalize_embeddings=True)
            return vecs.tolist()
        except Exception as e:
            logger.warning(f"Error batch encoding with SentenceTransformer: {e}")
            return [self.embed_text(t) for t in texts]


class HashProjectionEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    Lightweight hash-based n-gram projection baseline adapter.
    Preserved as a labeled deterministic fallback/benchmark.
    """
    dimension = 384
    provider_name = "hash_projection"
    model_name = "ngram-md5-proj-384"
    is_fallback = True
    status = "degraded"

    def embed_text(self, text: str) -> List[float]:
        if not text:
            return [0.0] * self.dimension

        tokens = text.lower().split()
        features = {}

        for i in range(len(tokens)):
            w = tokens[i]
            features[w] = features.get(w, 0) + 1.0
            if i < len(tokens) - 1:
                bg = f"{w}_{tokens[i+1]}"
                features[bg] = features.get(bg, 0) + 1.5

        vec = [0.0] * self.dimension
        for feat, weight in features.items():
            h = int(hashlib.md5(feat.encode('utf-8')).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if (h & 0x100) else -1.0
            vec[idx] += sign * weight

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]

        return vec

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_text(t) for t in texts]


_global_adapter: Optional[BaseEmbeddingAdapter] = None

def reset_embedding_adapter():
    """Resets the singleton adapter (useful in testing configuration changes)."""
    global _global_adapter
    _global_adapter = None


def get_embedding_adapter() -> BaseEmbeddingAdapter:
    """
    Factory providing the active embedding adapter based on Django settings.
    Guarantees explicit configuration validation and prevents silent hash degradation.
    """
    global _global_adapter
    if _global_adapter is not None:
        return _global_adapter

    provider = getattr(settings, 'EMBEDDING_PROVIDER', 'sentence-transformers').lower()

    if provider in ('sentence-transformers', 'local_transformer'):
        try:
            _global_adapter = SentenceTransformerEmbeddingAdapter()
            _global_adapter.is_fallback = False
            _global_adapter.status = "healthy"
            return _global_adapter
        except Exception as e:
            allow_fallback = getattr(settings, 'ALLOW_HASH_PROJECTION_FALLBACK', False)
            if not allow_fallback:
                logger.critical(
                    f"SentenceTransformer unavailable ({e}) and ALLOW_HASH_PROJECTION_FALLBACK=False. "
                    f"Refusing silent fallback to hash projection in production."
                )
                raise EmbeddingConfigurationError(
                    f"Embedding provider '{provider}' failed to initialize: {e}. "
                    f"Silent fallback to hash projection is disabled. Set ALLOW_HASH_PROJECTION_FALLBACK=True "
                    f"only if running isolated offline tests without PyTorch."
                ) from e

            logger.warning(
                f"[VISIBLE FALLBACK] SentenceTransformer unavailable ({e}). "
                f"ALLOW_HASH_PROJECTION_FALLBACK is enabled; utilizing HashProjection fallback."
            )
            _global_adapter = HashProjectionEmbeddingAdapter()
            _global_adapter.is_fallback = True
            _global_adapter.status = "degraded"
            return _global_adapter

    elif provider in ('hash_projection', 'ngram_hash'):
        _global_adapter = HashProjectionEmbeddingAdapter()
        _global_adapter.is_fallback = False
        _global_adapter.status = "benchmark_hash_mode"
        return _global_adapter

    else:
        raise EmbeddingConfigurationError(
            f"Unsupported EMBEDDING_PROVIDER '{provider}'. "
            f"Supported providers: 'sentence-transformers', 'hash_projection'."
        )


def validate_embedding_configuration() -> Dict[str, Any]:
    """
    Verifies that the active embedding provider is functional, dimensionally compatible (384),
    and strictly produces normalized vectors.
    """
    adapter = get_embedding_adapter()
    test_text = "LORE Enterprise Governance Engine verification sample text."
    vec = adapter.embed_text(test_text)

    dim = len(vec)
    norm = math.sqrt(sum(x * x for x in vec))
    is_normalized = abs(norm - 1.0) < 0.05 if norm > 0 else False

    compatible = (dim == 384) and is_normalized and (adapter.status != "degraded")

    return {
        "provider": adapter.provider_name,
        "model": adapter.model_name,
        "dimension": dim,
        "expected_dimension": 384,
        "is_normalized": is_normalized,
        "norm_value": round(norm, 4),
        "is_fallback": adapter.is_fallback,
        "status": adapter.status,
        "compatible": compatible,
    }

# Backward-compatibility alias
LocalEmbeddingService = get_embedding_adapter
