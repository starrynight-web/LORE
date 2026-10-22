import math
import hashlib
import logging
from typing import List, Optional
from django.conf import settings

logger = logging.getLogger(__name__)

class BaseEmbeddingAdapter:
    """Abstract interface for LORE Enterprise embedding adapters."""
    dimension: int = 384
    provider_name: str = "base"
    model_name: str = "base"

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
    def model(self):
        if SentenceTransformerEmbeddingAdapter._model_instance is None:
            self._load_model()
        return SentenceTransformerEmbeddingAdapter._model_instance

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

def get_embedding_adapter() -> BaseEmbeddingAdapter:
    """
    Factory providing the active embedding adapter based on Django settings.
    Defaults to SentenceTransformer with fallback to HashProjection.
    """
    global _global_adapter
    if _global_adapter is not None:
        return _global_adapter

    provider = getattr(settings, 'EMBEDDING_PROVIDER', 'sentence-transformers').lower()

    if provider in ('sentence-transformers', 'local_transformer'):
        try:
            _global_adapter = SentenceTransformerEmbeddingAdapter()
            return _global_adapter
        except Exception as e:
            logger.warning(f"SentenceTransformer unavailable ({e}). Falling back to HashProjection adapter.")
            _global_adapter = HashProjectionEmbeddingAdapter()
            return _global_adapter

    _global_adapter = HashProjectionEmbeddingAdapter()
    return _global_adapter

# Backward-compatibility alias
LocalEmbeddingService = get_embedding_adapter
