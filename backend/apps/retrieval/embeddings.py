import math
import hashlib
from typing import List

class LocalEmbeddingService:
    """
    High-performance embedding service with zero paid API requirement.
    Uses hash-based n-gram semantic projection to 384 dimensions.
    Can be seamlessly swapped with sentence-transformers or cloud embedding APIs.
    """
    DIMENSION = 384

    @classmethod
    def embed_text(cls, text: str) -> List[float]:
        if not text:
            return [0.0] * cls.DIMENSION

        # Tokenize and generate n-grams
        tokens = text.lower().split()
        features = {}

        # Unigrams & bigrams
        for i in range(len(tokens)):
            w = tokens[i]
            features[w] = features.get(w, 0) + 1.0
            if i < len(tokens) - 1:
                bg = f"{w}_{tokens[i+1]}"
                features[bg] = features.get(bg, 0) + 1.5

        # Project features into 384-dimensional dense space
        vec = [0.0] * cls.DIMENSION
        for feat, weight in features.items():
            h = int(hashlib.md5(feat.encode('utf-8')).hexdigest(), 16)
            idx = h % cls.DIMENSION
            sign = 1.0 if (h & 0x100) else -1.0
            vec[idx] += sign * weight

        # L2 normalize vector
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]

        return vec

    @classmethod
    def embed_batch(cls, texts: List[str]) -> List[List[float]]:
        return [cls.embed_text(t) for t in texts]
