"""
Embedding service — FastEmbed dense + sparse vector generation.

Dense:   BAAI/bge-small-en-v1.5   (384-dim, COSINE)
Sparse:  Qdrant/bm25              (BM25 keyword vectors)

Both models run locally — no API keys needed.
Models are downloaded on first use (~150 MB total).
"""

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Singleton — holds loaded FastEmbed models in memory."""

    _instance: "EmbeddingService | None" = None

    def __init__(self):
        from fastembed import TextEmbedding, SparseTextEmbedding

        settings = get_settings()

        logger.info(f"Loading dense model: {settings.dense_model}")
        self._dense = TextEmbedding(model_name=settings.dense_model)

        logger.info(f"Loading sparse model: {settings.sparse_model}")
        self._sparse = SparseTextEmbedding(model_name=settings.sparse_model)

        logger.info("Embedding models ready")

    @classmethod
    def get(cls) -> "EmbeddingService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Dense embeddings ──────────────────────────────────────────────────────

    def encode_dense(self, texts: list[str]) -> list[list[float]]:
        """Batch encode texts → list of 384-dim float vectors."""
        return [emb.tolist() for emb in self._dense.embed(texts)]

    def encode_query_dense(self, query: str) -> list[float]:
        """Encode a single search query (may apply model-specific prefix)."""
        return list(self._dense.query_embed(query))[0].tolist()

    # ── Sparse embeddings (BM25) ──────────────────────────────────────────────

    def encode_sparse(self, texts: list[str]) -> list[Any]:
        """Batch encode texts → list of SparseEmbedding (indices + values)."""
        return list(self._sparse.embed(texts))

    def encode_query_sparse(self, query: str) -> Any:
        """Encode a single query → SparseEmbedding."""
        return list(self._sparse.query_embed(query))[0]

    # ── Convenience: both at once ─────────────────────────────────────────────

    def encode_dual(self, texts: list[str]) -> tuple[list[list[float]], list[Any]]:
        """Generate dense + sparse vectors for the same texts."""
        dense = self.encode_dense(texts)
        sparse = self.encode_sparse(texts)
        return dense, sparse
