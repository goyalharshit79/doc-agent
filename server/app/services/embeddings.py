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

    def encode_dense(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        """Batch encode texts → list of 384-dim float vectors."""
        all_vecs: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            all_vecs.extend(emb.tolist() for emb in self._dense.embed(batch))
            if len(texts) > batch_size:
                logger.info(
                    f"  Dense batch {start // batch_size + 1}"
                    f"/{(len(texts) + batch_size - 1) // batch_size}"
                    f" ({len(batch)} texts)"
                )
        return all_vecs

    def encode_query_dense(self, query: str) -> list[float]:
        """Encode a single search query (may apply model-specific prefix)."""
        return list(self._dense.query_embed(query))[0].tolist()

    # ── Sparse embeddings (BM25) ──────────────────────────────────────────────

    def encode_sparse(self, texts: list[str], batch_size: int = 64) -> list[Any]:
        """Batch encode texts → list of SparseEmbedding (indices + values)."""
        all_vecs: list[Any] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            all_vecs.extend(self._sparse.embed(batch))
        return all_vecs

    def encode_query_sparse(self, query: str) -> Any:
        """Encode a single query → SparseEmbedding."""
        return list(self._sparse.query_embed(query))[0]

    # ── Convenience: both at once ─────────────────────────────────────────────

    # Max texts per ONNX call — keeps memory under control for large docs.
    EMBED_BATCH_SIZE = 64

    def encode_dual(self, texts: list[str]) -> tuple[list[list[float]], list[Any]]:
        """Generate dense + sparse vectors for the same texts (batched)."""
        bs = self.EMBED_BATCH_SIZE
        dense = self.encode_dense(texts, batch_size=bs)
        sparse = self.encode_sparse(texts, batch_size=bs)
        return dense, sparse
