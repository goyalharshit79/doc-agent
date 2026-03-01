import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.routes import router
from app.api.auth_routes import router as auth_router

logging.basicConfig(level=logging.INFO)


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

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
