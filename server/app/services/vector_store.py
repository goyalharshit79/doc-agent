"""
Vector store service — Qdrant hybrid search (dense + sparse).

Architecture:
  - Single collection "documents" with named vectors:
      dense  → BAAI/bge-small-en-v1.5  (384-dim, COSINE)
      sparse → Qdrant/bm25             (BM25 keyword vectors)
  - Payload indexes on: user_id, doc_id, doc_type
  - Hybrid retrieval: dense + sparse prefetch → RRF fusion
  - Strict metadata filtering on every search
  - Supabase for lightweight doc metadata (doc_id, name, type, user_id)
"""

import logging
import uuid as _uuid
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.core.config import get_settings
from app.services.embeddings import EmbeddingService

logger = logging.getLogger(__name__)


# ── Qdrant client ─────────────────────────────────────────────────────────────

@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    logger.info(f"Connecting to Qdrant at {settings.qdrant_host}:{settings.qdrant_port}")
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


# ── Collection management ─────────────────────────────────────────────────────

def ensure_collection() -> str:
    """
    Create the unified 'documents' collection if it doesn't exist.
    Sets up named vectors (dense + sparse) and payload indexes.
    Returns the collection name.
    """
    settings = get_settings()
    name     = settings.collection_name
    client   = get_qdrant_client()

    if client.collection_exists(name):
        return name

    logger.info(f"Creating collection '{name}' with hybrid vectors…")

    client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": models.VectorParams(
                size=384,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                modifier=models.Modifier.IDF,   # complete BM25 scoring
            ),
        },
    )

    # Payload indexes → fast filtered search
    for field in ("user_id", "doc_id", "doc_type"):
        client.create_payload_index(
            collection_name=name,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    logger.info(f"Collection '{name}' ready with dense + sparse vectors + 3 payload indexes")
    return name


def doc_vectors_exist(doc_id: str) -> bool:
    """Check if any vectors already exist for this doc_id (idempotency check)."""
    settings = get_settings()
    client   = get_qdrant_client()
    name     = settings.collection_name

    if not client.collection_exists(name):
        return False

    result = client.scroll(
        collection_name=name,
        scroll_filter=models.Filter(must=[
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
        ]),
        limit=1,
        with_payload=False,
    )
    return len(result[0]) > 0


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _get_supabase():
    from supabase import create_client
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


def doc_exists_for_user(doc_id: str, user_id: str) -> bool:
    try:
        sb = _get_supabase()
        result = (
            sb.table("documents")
            .select("doc_id")
            .eq("doc_id", doc_id)
            .eq("user_id", user_id)
            .execute()
        )
        return len(result.data) > 0
    except Exception as e:
        logger.warning(f"Supabase check failed: {e}")
        return False


def get_user_documents(user_id: str) -> list[dict]:
    try:
        sb = _get_supabase()
        result = (
            sb.table("documents")
            .select("doc_id, doc_name, doc_type, num_chunks, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.warning(f"Supabase get_user_documents failed: {e}")
        return []


def save_doc_meta(doc_id: str, doc_name: str, num_chunks: int, user_id: str, doc_type: str = "general"):
    try:
        sb = _get_supabase()
        sb.table("documents").upsert({
            "doc_id":     doc_id,
            "doc_name":   doc_name,
            "doc_type":   doc_type,
            "num_chunks": num_chunks,
            "user_id":    user_id,
        }).execute()
    except Exception as e:
        logger.warning(f"Supabase doc meta save failed: {e}")


# ── Embed & store ─────────────────────────────────────────────────────────────

def embed_and_store(chunks: list[dict]) -> int:
    """
    Generate dense + sparse embeddings for all chunks and upsert
    into the unified Qdrant collection with full metadata payloads.
    """
    if not chunks:
        return 0

    col_name = ensure_collection()
    emb_svc  = EmbeddingService.get()
    client   = get_qdrant_client()

    texts = [c["text"] for c in chunks]
    logger.info(f"Generating dual embeddings for {len(texts)} chunks…")

    dense_vecs, sparse_vecs = emb_svc.encode_dual(texts)

    points = []
    for i, chunk in enumerate(chunks):
        point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, chunk["chunk_id"]))

        sv = sparse_vecs[i]
        points.append(models.PointStruct(
            id=point_id,
            vector={
                "dense":  dense_vecs[i],
                "sparse": models.SparseVector(
                    indices=sv.indices.tolist(),
                    values=sv.values.tolist(),
                ),
            },
            payload={
                "chunk_id":    chunk["chunk_id"],
                "text":        chunk["text"],
                "doc_id":      chunk["doc_id"],
                "doc_name":    chunk["doc_name"],
                "doc_type":    chunk.get("doc_type", "general"),
                "user_id":     chunk.get("user_id", ""),
                "page_number": chunk.get("page_number"),
                "heading":     chunk.get("heading") or "",
            },
        ))

    # Qdrant upsert handles batching internally
    client.upsert(collection_name=col_name, points=points, wait=True)
    logger.info(f"Upserted {len(points)} points into '{col_name}'")
    return len(points)


# ── Hybrid search ─────────────────────────────────────────────────────────────

def hybrid_search(
    query: str,
    user_id: str,
    doc_ids: list[str],
    top_k: int | None = None,
) -> list:
    """
    Hybrid retrieval: dense + sparse with RRF fusion.
    Strict metadata filtering ensures user_id AND doc_id(s) match.
    Returns list of Qdrant ScoredPoint objects.
    """
    if top_k is None:
        top_k = get_settings().retrieval_top_k

    col_name = ensure_collection()
    emb_svc  = EmbeddingService.get()
    client   = get_qdrant_client()

    # Encode query
    dense_qv  = emb_svc.encode_query_dense(query)
    sparse_qv = emb_svc.encode_query_sparse(query)

    # Strict metadata filter — use exact match for single doc, MatchAny for multi
    doc_filter = (
        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_ids[0]))
        if len(doc_ids) == 1
        else models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids))
    )
    must_filter = models.Filter(must=[
        models.FieldCondition(
            key="user_id",
            match=models.MatchValue(value=user_id),
        ),
        doc_filter,
    ])

    sparse_vector = models.SparseVector(
        indices=sparse_qv.indices.tolist(),
        values=sparse_qv.values.tolist(),
    )

    results = client.query_points(
        collection_name=col_name,
        prefetch=[
            # Dense semantic search
            models.Prefetch(
                query=dense_qv,
                using="dense",
                limit=top_k + 5,       # slight overfetch for better fusion
                filter=must_filter,
            ),
            # Sparse keyword search (BM25)
            models.Prefetch(
                query=sparse_vector,
                using="sparse",
                limit=top_k + 5,
                filter=must_filter,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )

    logger.info(f"Hybrid search returned {len(results.points)} results for '{query[:60]}'")
    return results.points


def keyword_search(
    query: str,
    user_id: str,
    doc_ids: list[str],
    top_k: int = 10,
) -> list:
    """
    Pure sparse / keyword search — for exact term matching.
    Uses BM25 sparse vectors only (no semantic component).
    """
    col_name = ensure_collection()
    emb_svc  = EmbeddingService.get()
    client   = get_qdrant_client()

    sparse_qv = emb_svc.encode_query_sparse(query)

    doc_filter = (
        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_ids[0]))
        if len(doc_ids) == 1
        else models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids))
    )
    must_filter = models.Filter(must=[
        models.FieldCondition(
            key="user_id",
            match=models.MatchValue(value=user_id),
        ),
        doc_filter,
    ])

    results = client.query_points(
        collection_name=col_name,
        query=models.SparseVector(
            indices=sparse_qv.indices.tolist(),
            values=sparse_qv.values.tolist(),
        ),
        using="sparse",
        query_filter=must_filter,
        limit=top_k,
        with_payload=True,
    )

    logger.info(f"Keyword search returned {len(results.points)} results for '{query[:60]}'")
    return results.points


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_document_vectors(doc_id: str, user_id: str):
    """Remove all vectors for a specific document (for re-upload or cleanup)."""
    settings = get_settings()
    client   = get_qdrant_client()
    name     = settings.collection_name

    if not client.collection_exists(name):
        return

    client.delete(
        collection_name=name,
        points_selector=models.FilterSelector(
            filter=models.Filter(must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            ])
        ),
    )
    logger.info(f"Deleted vectors for doc_id={doc_id}")


def delete_doc_meta(doc_id: str, user_id: str):
    """Delete document metadata from Supabase."""
    try:
        sb = _get_supabase()
        sb.table("documents").delete().eq("doc_id", doc_id).eq("user_id", user_id).execute()
        logger.info(f"Deleted Supabase metadata for doc_id={doc_id}")
    except Exception as e:
        logger.warning(f"Supabase doc meta delete failed: {e}")
        raise


def delete_document_full(doc_id: str, user_id: str):
    """Delete document from both Qdrant (embeddings) and Supabase (metadata)."""
    delete_document_vectors(doc_id, user_id)
    delete_doc_meta(doc_id, user_id)
    logger.info(f"Fully deleted doc_id={doc_id} for user={user_id[:8]}…")


# ── Upload orchestrator ───────────────────────────────────────────────────────

def process_upload(
    chunks: list[dict],
    doc_id: str,
    doc_name: str,
    user_id: str,
    doc_type: str = "general",
) -> dict:
    """
    Full upload pipeline: check idempotency → embed → store → save meta.
    """
    already_existed = doc_vectors_exist(doc_id)

    if already_existed:
        logger.info(f"Doc {doc_id} already in Qdrant — skipping embed")
        num_chunks = len(chunks)
    else:
        num_chunks = embed_and_store(chunks)
        logger.info(f"Embedded {num_chunks} chunks for doc {doc_id}")

    # Always upsert Supabase metadata
    save_doc_meta(doc_id, doc_name, num_chunks, user_id, doc_type)

    return {
        "doc_id":          doc_id,
        "doc_name":        doc_name,
        "doc_type":        doc_type,
        "num_chunks":      num_chunks,
        "already_existed": already_existed,
    }
