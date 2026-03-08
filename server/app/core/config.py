from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    gcp_project: str
    gcp_location: str = "us-central1"
    vertex_index_endpoint_id: str
    vertex_index_id: str
    vertex_deployed_index_id: str
    supabase_url: str
    supabase_service_key: str   # sb_secret_... from Supabase dashboard
    secret_key: str
    cors_origins: str = "http://localhost:5173"

    # FastEmbed models
    dense_model: str = "BAAI/bge-small-en-v1.5"          # 384-dim dense vectors
    sparse_model: str = "Qdrant/bm25"                     # BM25 sparse vectors

    # Re-ranker (local HuggingFace CrossEncoder)
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Retrieval
    retrieval_top_k: int = 15     # hybrid search → 15 candidates
    rerank_top_k: int = 5         # cross-encoder keeps top 5

    # LLM
    llm_model: str = "gemini-2.5-pro"
    query_rewrite_model: str = "gemini-2.5-flash"    # cheap/fast for rewrites

    # ── Razorpay ─────────────────────────────────────────────────────────────
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_plan_id: str = ""           # Razorpay Plan ID for Pro subscription
    razorpay_webhook_secret: str = ""

    # ── Plan limits ──────────────────────────────────────────────────────────
    free_max_documents: int = 1
    free_max_queries_per_day: int = 10
    pro_max_documents: int = 20

    # ── Admin ────────────────────────────────────────────────────────────────
    admin_email: str = "goyalharshit79@gmail.com"

    # Adaptive chunk sizes (words) per document type
    chunk_config: dict = {
        "contract":       {"size": 600, "overlap": 100},
        "medical_report": {"size": 500, "overlap": 80},
        "book":           {"size": 800, "overlap": 150},
        "resume":         {"size": 200, "overlap": 30},
        "general":        {"size": 500, "overlap": 80},
    }

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
