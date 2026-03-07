import logging
import time
import uuid as _uuid
from functools import lru_cache

from google.cloud import aiplatform
from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import (
    Namespace,
    NumericNamespace,
)
from google.cloud.aiplatform_v1.types.index import IndexDatapoint

from app.core.config import get_settings
from app.core.retry import gcp_retry
from app.services.embeddings import EmbeddingService

logger = logging.getLogger(__name__)


# ── Vertex AI client ──────────────────────────────────────────────────────────

@lru_cache
def _init_vertex():
    settings = get_settings()
    logger.info(f"Connecting to Vertex AI in {settings.gcp_project} / {settings.gcp_location}")
    aiplatform.init(project=settings.gcp_project, location=settings.gcp_location)

@lru_cache
def get_vertex_endpoint() -> aiplatform.MatchingEngineIndexEndpoint:
    _init_vertex()
    settings = get_settings()
    return aiplatform.MatchingEngineIndexEndpoint(
        index_endpoint_name=settings.vertex_index_endpoint_id
    )

@lru_cache
def get_vertex_index() -> aiplatform.MatchingEngineIndex:
    _init_vertex()
    settings = get_settings()
    return aiplatform.MatchingEngineIndex(
        index_name=settings.vertex_index_id
    )

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


def get_doc_meta_by_id(doc_id: str, user_id: str) -> dict | None:
    try:
        sb = _get_supabase()
        result = (
            sb.table("documents")
            .select("doc_id, doc_name, doc_type, num_chunks")
            .eq("doc_id", doc_id)
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"Supabase get_doc_meta_by_id failed: {e}")
        return None


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
    Generate dense embeddings for all chunks and upsert
    into Vertex AI Vector Search. Payloads are saved to Supabase 'document_chunks'.
    """
    if not chunks:
        return 0

    emb_svc  = EmbeddingService.get()
    index    = get_vertex_index()
    sb       = _get_supabase()
    settings = get_settings()

    texts = [c["text"] for c in chunks]
    logger.info(f"Generating embeddings for {len(texts)} chunks…")

    # Hybrid Search requires FeatureVector for sparse data in Google Cloud
    # FastEmbed returns SparseEmbedding(indices, values). We must map to dict.
    t0 = time.perf_counter()
    dense_vecs, sparse_vecs = emb_svc.encode_dual(texts)
    logger.info(f"⏱  EMBEDDING      {time.perf_counter() - t0:.2f}s  ({len(texts)} chunks → dense+sparse)")

    points = []
    db_chunks = []
    
    for i, chunk in enumerate(chunks):
        point_id = chunk["chunk_id"]

        # Convert sparse vector values to floats for JSON serialization
        sparse_dict = {
            # Vertex AI expects string indices or stringified integers for sparse tokens
            str(idx): float(val) 
            for idx, val in zip(sparse_vecs[i].indices, sparse_vecs[i].values)
        }

        points.append(IndexDatapoint(
            datapoint_id=point_id,
            feature_vector=dense_vecs[i],
            sparse_embedding=IndexDatapoint.SparseEmbedding(
                values=list(sparse_dict.values()),
                dimensions=[int(k) for k in sparse_dict.keys()]
            ),
            restricts=[
                IndexDatapoint.Restriction(namespace="user_id", allow_list=[chunk.get("user_id", "")]),
                IndexDatapoint.Restriction(namespace="doc_id", allow_list=[chunk["doc_id"]]),
            ]
        ))
        
        db_chunks.append({
            "chunk_id": point_id,
            "doc_id": chunk["doc_id"],
            "user_id": chunk.get("user_id", ""),
            "text": chunk["text"],
            "doc_name": chunk["doc_name"],
            "page_number": chunk.get("page_number"),
            "heading": chunk.get("heading") or "",
        })

    # Vertex AI Upsert (with exponential backoff)
    @gcp_retry
    def _upsert_to_vertex(idx, pts):
        idx.upsert_datapoints(datapoints=pts)

    t0 = time.perf_counter()
    _upsert_to_vertex(index, points)
    logger.info(f"⏱  VERTEX UPSERT  {time.perf_counter() - t0:.2f}s  ({len(points)} vectors)")

    # Store chunk text payloads in Supabase — this MUST succeed,
    # otherwise search returns vectors without text ("Payload missing").
    t0 = time.perf_counter()
    sb.table("document_chunks").upsert(db_chunks).execute()
    logger.info(f"⏱  SUPABASE STORE {time.perf_counter() - t0:.2f}s  ({len(db_chunks)} chunks)")

    return len(points)


# ── Search ────────────────────────────────────────────────────────────────────

# Fake ScoredPoint class to match Qdrant's return type for llm.py compatibility
class ScoredPoint:
    def __init__(self, point_id, score, payload):
        self.id = point_id
        self.score = score
        self.payload = payload

def hybrid_search(
    query: str,
    user_id: str,
    doc_ids: list[str],
    top_k: int | None = None,
) -> list:
    """
    Vertex AI retrieval: Dense search mapped to Qdrant-like return formats.
    """
    if top_k is None:
        top_k = get_settings().retrieval_top_k

    emb_svc  = EmbeddingService.get()
    endpoint = get_vertex_endpoint()
    sb       = _get_supabase()
    settings = get_settings()

    # Encode query natively into both spaces
    t0 = time.perf_counter()
    dense_qv  = emb_svc.encode_query_dense(query)
    sparse_qv = emb_svc.encode_query_sparse(query)
    logger.info(f"⏱  QUERY EMBED    {time.perf_counter() - t0:.2f}s")

    # Restricts for metadata
    string_restricts = [
        Namespace(name="user_id", allow_tokens=[user_id]),
        Namespace(name="doc_id", allow_tokens=doc_ids)
    ]

    # Convert sparse query for Vertex AI
    sparse_query = {
        str(idx): float(val)
        for idx, val in zip(sparse_qv.indices, sparse_qv.values)
    }

    # Execute Hybrid Query (Requires Vertex AI Search 2.0 capabilities)
    from google.cloud.aiplatform.matching_engine.matching_engine_index_endpoint import HybridQuery
    
    hq = HybridQuery(
        dense_embedding=dense_qv,
        sparse_embedding_dimensions=[int(k) for k in sparse_query.keys()],
        sparse_embedding_values=list(sparse_query.values()),
        rrf_ranking_alpha=0.5, # 0.5 balances dense and sparse
    )

    # Search with exponential backoff on transient failures
    @gcp_retry
    def _find_neighbors(ep, **kwargs):
        return ep.find_neighbors(**kwargs)

    t0 = time.perf_counter()
    results = _find_neighbors(
        endpoint,
        deployed_index_id=settings.vertex_deployed_index_id,
        queries=[hq],
        num_neighbors=top_k + 5,
        filter=string_restricts,
    )
    logger.info(f"⏱  VERTEX SEARCH  {time.perf_counter() - t0:.2f}s")

    if not results or not results[0]:
        return []

    # Vertex AI returns a list of neighbors for each query.
    neighbors = results[0]

    # Fetch payloads from Supabase
    neighbor_ids = [n.id for n in neighbors]

    t0 = time.perf_counter()
    try:
        chunk_res = sb.table("document_chunks").select("*").in_("chunk_id", neighbor_ids).execute()
        chunk_map = {c["chunk_id"]: c for c in chunk_res.data}
    except Exception as e:
        logger.error(f"Failed to fetch chunk payloads: {e}")
        chunk_map = {}
    logger.info(f"⏱  SUPABASE FETCH {time.perf_counter() - t0:.2f}s  ({len(chunk_map)} payloads)")

    scored_points = []
    for n in neighbors:
        payload = chunk_map.get(n.id, {
            "chunk_id": n.id,
            "text": "Payload missing",
            "doc_id": "Unknown",
            "doc_name": "Unknown"
        })
        scored_points.append(ScoredPoint(point_id=n.id, score=n.distance, payload=payload))

    logger.info(f"Vertex AI Search returned {len(scored_points)} results for '{query[:60]}'")
    return scored_points

# ── Delete ────────────────────────────────────────────────────────────────────

def delete_document_full(doc_id: str, user_id: str):
    """Delete document from both Vertex AI (embeddings) and Supabase (metadata)."""
    sb = _get_supabase()
    index = get_vertex_index()

    try:
        # Fetch chunk IDs to delete from Vertex
        res = sb.table("document_chunks").select("chunk_id").eq("doc_id", doc_id).eq("user_id", user_id).execute()
        chunk_ids = [c["chunk_id"] for c in res.data]

        if chunk_ids:
            @gcp_retry
            def _remove_from_vertex(idx, ids):
                idx.remove_datapoints(datapoint_ids=ids)

            _remove_from_vertex(index, chunk_ids)
            sb.table("document_chunks").delete().in_("chunk_id", chunk_ids).execute()
            
        sb.table("documents").delete().eq("doc_id", doc_id).eq("user_id", user_id).execute()
        logger.info(f"Fully deleted doc_id={doc_id} for user={user_id[:8]}…")
    except Exception as e:
        logger.warning(f"Delete failed: {e}")


def doc_vectors_exist(doc_id: str) -> bool:
    """Check if document_chunks exist in Supabase (proxy for Vertex idempotency)."""
    try:
        sb = _get_supabase()
        res = sb.table("document_chunks").select("chunk_id").eq("doc_id", doc_id).limit(1).execute()
        return len(res.data) > 0
    except Exception:
        return False

# ── Upload orchestrator ───────────────────────────────────────────────────────

def process_upload(
    chunks: list[dict],
    doc_id: str,
    doc_name: str,
    user_id: str,
    doc_type: str = "general",
) -> dict:
    already_existed = doc_vectors_exist(doc_id)

    if already_existed:
        logger.info(f"Doc {doc_id} already exists — skipping embed")
        num_chunks = len(chunks)
    else:
        # IMPORTANT: save document metadata FIRST so the FK from
        # document_chunks.doc_id → documents.doc_id is satisfied.
        save_doc_meta(doc_id, doc_name, len(chunks), user_id, doc_type)

        num_chunks = embed_and_store(chunks)
        logger.info(f"Embedded {num_chunks} chunks for doc {doc_id}")

        # Update chunk count in case it differs after embedding
        save_doc_meta(doc_id, doc_name, num_chunks, user_id, doc_type)

    return {
        "doc_id":          doc_id,
        "doc_name":        doc_name,
        "doc_type":        doc_type,
        "num_chunks":      num_chunks,
        "already_existed": already_existed,
    }
