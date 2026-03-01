import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.auth import get_current_user_id
from app.models.schemas import AskRequest, AskResponse, DocMeta, UploadResponse
from app.services.parser import parse_document
from app.services.vector_store import get_user_documents, process_upload, similarity_search, get_qdrant_client
from app.services.llm import run_rag

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ── POST /upload ───────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),   # ← auth required
):
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        doc_id, chunks = await asyncio.to_thread(
            parse_document, file_bytes, file.filename, len(file_bytes)
        )
        if not chunks:
            raise HTTPException(status_code=422, detail="No text could be extracted")

        result = await asyncio.to_thread(
            process_upload, chunks, doc_id, file.filename, user_id  # ← pass user_id
        )

        return UploadResponse(
            doc_id     = result["doc_id"],
            doc_name   = result["doc_name"],
            num_chunks = result["num_chunks"],
            message    = "Loaded from cache" if result["already_existed"] else f"Indexed {result['num_chunks']} chunks",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Upload failed for {file.filename}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


# ── GET /documents ─────────────────────────────────────────────────────────────

@router.get("/documents", response_model=list[DocMeta])
async def list_documents(user_id: str = Depends(get_current_user_id)):
    """Return all documents the current user has uploaded."""
    log_message = "This is a log message from the FastAPI server!"
    docs = await asyncio.to_thread(get_user_documents, user_id)
    return docs


# ── POST /ask ──────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=AskResponse)
async def ask_question(
    request: AskRequest,
    user_id: str = Depends(get_current_user_id),   # ← auth required
):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if not request.doc_ids:
        raise HTTPException(status_code=400, detail="At least one doc_id is required")

    # Verify all requested doc_ids belong to this user — prevents cross-user access
    user_docs = await asyncio.to_thread(get_user_documents, user_id)
    user_doc_ids = {d["doc_id"] for d in user_docs}
    unauthorized = [did for did in request.doc_ids if did not in user_doc_ids]
    if unauthorized:
        raise HTTPException(status_code=403, detail="Access denied to one or more documents")

    try:
        response = await asyncio.to_thread(run_rag, request)
        return response
    except Exception as e:
        logger.exception("RAG pipeline failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate answer: {str(e)}")


# ── GET /debug/qdrant — inspect vector store ──────────────────────────────────

@router.get("/debug/qdrant")
async def debug_qdrant():
    """Shows all Qdrant collections and their vector counts (dev only)."""
    client = get_qdrant_client()
    collections = client.get_collections().collections
    result = []
    for c in collections:
        info = client.get_collection(c.name)
        count = info.points_count or 0
        sample_ids = []
        sample_docs = []
        if count > 0:
            scroll = client.scroll(collection_name=c.name, limit=2, with_payload=True)
            for point in scroll[0]:
                sample_ids.append(str(point.id))
                text = (point.payload or {}).get("text", "")
                sample_docs.append(text[:100] + "..." if len(text) > 100 else text)
        result.append({
            "name": c.name,
            "count": count,
            "sample_ids": sample_ids,
            "sample_docs": sample_docs,
        })
    return {"total_collections": len(result), "collections": result}
