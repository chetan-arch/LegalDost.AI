"""Embedding backends.

``HashingEmbedder`` is the default: deterministic, offline, no model download. It hashes word
unigrams/bigrams and character trigrams into a fixed-size vector. It captures surface and
morphological similarity, **not** true semantics; treat it as a development fallback. For
production, configure a multilingual model (``EMBEDDING_BACKEND=sentence-transformers``) and run
``legaldost reindex-embeddings``.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from typing import Protocol

from legaldost.config import get_settings
from legaldost.textutil import content_tokens, normalize


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _features(self, text: str) -> list[str]:
        tokens = content_tokens(text)
        feats = [f"w:{t}" for t in tokens]
        feats += [f"b:{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        squashed = normalize(text).replace(" ", "_")
        feats += [f"c:{squashed[i : i + 3]}" for i in range(max(0, len(squashed) - 2))]
        return feats

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for feat in self._features(text):
                digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] & 1 else -1.0
                weight = 0.5 if feat.startswith("c:") else 1.0
                vec[idx] += sign * weight
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SentenceTransformerEmbedder:  # pragma: no cover - optional dependency, not exercised in CI
    def __init__(self, model_name: str, dim: int) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = dim
        self.name = f"st:{model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        result = [list(map(float, v)) for v in vectors]
        if result and len(result[0]) != self.dim:
            raise ValueError(f"model returns {len(result[0])} dims but EMBEDDING_DIM={self.dim}")
        return result


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_backend == "sentence-transformers":
        return SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_dim)
    return HashingEmbedder(settings.embedding_dim)
