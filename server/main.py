import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.routes import router
from app.api.auth_routes import router as auth_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Thread pool for asyncio.to_thread() ──────────────────────────────────────
# Default pool is too small (os.cpu_count() + 4) for I/O-heavy GCP calls.
# A bigger pool lets multiple uploads/asks run in parallel without blocking.
_THREAD_POOL_SIZE = int(os.environ.get("THREAD_POOL_SIZE", 16))


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title       = "DocAgent API",
        description = "Document intelligence backend — parse, embed, answer, cite.",
        version     = "0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins     = settings.cors_origins.split(","),
        allow_credentials = True,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
    )

    app.include_router(auth_router, prefix="/api")   # /api/auth/signup, /api/auth/login
    app.include_router(router, prefix="/api")        # /api/upload, /api/ask, /api/documents

    @app.on_event("startup")
    async def _setup_thread_pool():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=_THREAD_POOL_SIZE)
        loop.set_default_executor(executor)
        logger.info(f"Thread pool: {_THREAD_POOL_SIZE} workers for asyncio.to_thread()")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
