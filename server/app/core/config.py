from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    gemini_api_key: str
    supabase_url: str
    supabase_service_key: str   # sb_secret_... from Supabase dashboard
    secret_key: str
    cors_origins: str = "http://localhost:5173"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    collection_name: str = "documents"    # single unified collection

    # FastEmbed models
    dense_model: str = "BAAI/bge-small-en-v1.5"          # 384-dim dense vectors
    sparse_model: str = "Qdrant/bm25"                     # BM25 sparse vectors

    # Re-ranker (local HuggingFace CrossEncoder)
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Retrieval
    retrieval_top_k: int = 15     # hybrid search → 15 candidates
    rerank_top_k: int = 3         # cross-encoder keeps top 3

    # LLM
    llm_model: str = "gemini-2.5-flash"
    query_rewrite_model: str = "gemini-2.0-flash-lite"    # cheap/fast for rewrites

    # Adaptive chunk sizes (words) per document type
    chunk_config: dict = {
        "contract":       {"size": 600, "overlap": 100},
        "medical_report": {"size": 500, "overlap": 80},
        "book":           {"size": 800, "overlap": 150},
        "resume":         {"size": 300, "overlap": 50},
        "general":        {"size": 500, "overlap": 80},
    }

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
