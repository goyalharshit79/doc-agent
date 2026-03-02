"""
Re-ranker service — local HuggingFace Cross-Encoder.

Takes the user's original question + N retrieved chunks, scores every
(query, chunk_text) pair with a cross-encoder, and returns the top-K
highest-scoring results.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2  (~80 MB, first-use download)
"""

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Reranker:
    """Singleton — holds the CrossEncoder model in memory."""

    _instance: "Reranker | None" = None

    def __init__(self):
        from sentence_transformers import CrossEncoder

        settings = get_settings()
        logger.info(f"Loading reranker model: {settings.reranker_model}")
        self._model = CrossEncoder(settings.reranker_model)
        logger.info("Reranker model ready")

    @classmethod
    def get(cls) -> "Reranker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def rerank(
        self,
        query: str,
        results: list,
        top_k: int | None = None,
    ) -> list[tuple]:
        """
        Re-rank Qdrant ScoredPoint results using the cross-encoder.

        Parameters
        ----------
        query   : the user's original question (NOT the transformed query)
        results : list of Qdrant ScoredPoint objects (must have .payload["text"])
        top_k   : how many to keep (default: config.rerank_top_k)

        Returns
        -------
        list of (ScoredPoint, cross_encoder_score) tuples, descending by score.
        """
        if not results:
            return []

        if top_k is None:
            top_k = get_settings().rerank_top_k

        # Build (query, passage) pairs
        pairs = [(query, r.payload["text"]) for r in results]
        scores = self._model.predict(pairs)

        scored = sorted(
            zip(results, scores.tolist()),
            key=lambda x: x[1],
            reverse=True,
        )

        logger.info(
            f"Reranked {len(results)} → top {top_k}  "
            f"(best={scored[0][1]:.3f}, worst-kept={scored[min(top_k,len(scored))-1][1]:.3f})"
        )
        return scored[:top_k]
