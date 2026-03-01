"""
Vector store service.

Responsibilities:
  - Embed chunks using sentence-transformers
  - Store vectors + text in Qdrant (via HTTP client → standalone server)
  - Store lightweight doc metadata in Supabase (doc_id, name, chunk count, user_id)
  - On upload: check Qdrant first → skip re-embedding if already present
  - Similarity search: scoped to explicit doc_ids (always user-owned)
"""

import logging
import uuid as _uuid
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# all-MiniLM-L6-v2 produces 384-dim vectors
VECTOR_SIZE = 384


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    settings = get_settings()
    logger.info(f"Loading embedding model: {settings.embedding_model}")
    return SentenceTransformer(settings.embedding_model)


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    logger.info(f"Connecting to Qdrant at {settings.qdrant_host}:{settings.qdrant_port}")
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def _collection_name(doc_id: str) -> str:
    """Qdrant collection names must match [a-zA-Z0-9_-]. Replace dots etc."""
    return f"doc_{doc_id}".replace(".", "_").replace(" ", "_")


def ensure_collection(doc_id: str) -> str:
    """Create collection if it doesn't exist. Returns the collection name."""
    client = get_qdrant_client()
    name = _collection_name(doc_id)
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info(f"Created Qdrant collection: {name}")
    return name


def collection_count(doc_id: str) -> int:
    """Return number of points in a collection (0 if it doesn't exist)."""
    client = get_qdrant_client()
    name = _collection_name(doc_id)
    if not client.collection_exists(name):
        return 0
    info = client.get_collection(name)
    return info.points_count or 0


# ── Supabase helpers ───────────────────────────────────────────────────────────

def get_supabase():
    from supabase import create_client
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


def doc_exists_for_user(doc_id: str, user_id: str) -> bool:
    """Check if this user has already processed this document."""
    try:
        sb = get_supabase()
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
    """Return all documents belonging to a user."""
    try:
        sb = get_supabase()
        result = (
            sb.table("documents")
            .select("doc_id, doc_name, num_chunks, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data
    except Exception as e:
        logger.warning(f"Supabase get_user_documents failed: {e}")
        return []


def save_doc_meta(doc_id: str, doc_name: str, num_chunks: int, user_id: str):
    try:
        sb = get_supabase()
        sb.table("documents").upsert({
            "doc_id":     doc_id,
            "doc_name":   doc_name,
            "num_chunks": num_chunks,
            "user_id":    user_id,
        }).execute()
    except Exception as e:
        logger.warning(f"Supabase doc meta save failed: {e}")


# ── Core operations ────────────────────────────────────────────────────────────

def embed_and_store(chunks: list[dict]) -> int:
    if not chunks:
        return 0

    model = get_embedding_model()
    texts = [c["text"] for c in chunks]

    logger.info(f"Embedding {len(texts)} chunks...")
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False).tolist()

    from itertools import groupby
    sorted_chunks = sorted(zip(chunks, embeddings), key=lambda x: x[0]["doc_id"])

    for doc_id, group in groupby(sorted_chunks, key=lambda x: x[0]["doc_id"]):
        col_name = ensure_collection(doc_id)
        group = list(group)

        points = []
        for chunk, emb in group:
            # Qdrant requires UUID or int IDs — generate a deterministic UUID from chunk_id
            point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, chunk["chunk_id"]))
            points.append(PointStruct(
                id=point_id,
                vector=emb,
                payload={
                    "chunk_id":        chunk["chunk_id"],
                    "text":            chunk["text"],
                    "page":            str(chunk.get("page") or ""),
                    "heading":         chunk.get("heading") or "",
                    "paragraph_index": str(chunk.get("paragraph_index") or ""),
                    "doc_name":        chunk["doc_name"],
                },
            ))

        # Qdrant upsert handles batching internally
        client = get_qdrant_client()
        client.upsert(collection_name=col_name, points=points)

    return len(chunks)


def similarity_search(query: str, doc_ids: list[str], top_k: int = 6) -> list[dict]:
    """
    Search is always scoped to explicit doc_ids.
    Since doc_ids are validated against user_id at the route level,
    this never touches another user's data.
    """
    model = get_embedding_model()
    query_embedding = model.encode([query])[0].tolist()

    results = []
    per_doc_k = max(2, top_k // len(doc_ids))
    client = get_qdrant_client()

    for doc_id in doc_ids:
        try:
            col_name = _collection_name(doc_id)
            if not client.collection_exists(col_name):
                logger.warning(f"Collection {col_name} not found, skipping")
                continue

            hits = client.query_points(
                collection_name=col_name,
                query=query_embedding,
                limit=per_doc_k,
                with_payload=True,
            ).points

            for hit in hits:
                payload = hit.payload or {}
                results.append({
                    "chunk_id": payload.get("chunk_id", str(hit.id)),
                    "doc_id":   doc_id,
                    "doc_name": payload.get("doc_name", ""),
                    "page":     int(payload["page"]) if payload.get("page") else None,
                    "heading":  payload.get("heading") or None,
                    "text":     payload.get("text", ""),
                    "score":    hit.score,
                })
        except Exception as e:
            logger.warning(f"Search failed for doc {doc_id}: {e}")

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


# ── Upload orchestrator ────────────────────────────────────────────────────────

def process_upload(chunks: list[dict], doc_id: str, doc_name: str, user_id: str) -> dict:
    # Check if vectors already exist in Qdrant
    existing_count = collection_count(doc_id)
    already_existed = existing_count > 0

    if already_existed:
        logger.info(f"Doc {doc_id} already in Qdrant ({existing_count} vectors) — skipping embed")
    else:
        embed_and_store(chunks)
        logger.info(f"Embedded {len(chunks)} chunks for doc {doc_id}")

    # Always ensure Supabase has the doc metadata (lightweight, one row)
    save_doc_meta(doc_id, doc_name, len(chunks) if not already_existed else existing_count, user_id)

    return {
        "doc_id":          doc_id,
        "doc_name":        doc_name,
        "num_chunks":      len(chunks) if not already_existed else existing_count,
        "already_existed": already_existed,
    }
