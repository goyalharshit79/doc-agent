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

    # Chunking
    chunk_size: int = 400
    chunk_overlap: int = 50
    top_k_chunks: int = 6

    # Model
    llm_model: str = "gemini-2.5-flash"
    embedding_model: str = "all-MiniLM-L6-v2"

    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
