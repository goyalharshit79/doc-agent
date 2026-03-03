import asyncio
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.auth import get_current_user_id
from app.models.schemas import AskRequest, AskResponse, DocMeta, DocType, UploadResponse
from app.services.parser import parse_document
from app.services.vector_store import (
    get_user_documents,
    process_upload,
    get_qdrant_client,
    delete_document_full,
    doc_exists_for_user,
)
from app.services.llm import run_rag

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


# ── POST /upload ──────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form("general"),               # ← user selects from dropdown
    user_id: str = Depends(get_current_user_id),
):
    # Validate extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    # Validate doc_type
    try:
        doc_type_enum = DocType(doc_type)
    except ValueError:
        valid = [e.value for e in DocType]
        raise HTTPException(status_code=400, detail=f"Invalid doc_type. Must be one of: {valid}")

    # Read + validate file
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        # Parse (unstructured → Markdown → adaptive chunking)
        doc_id, chunks = await asyncio.to_thread(
            parse_document,
            file_bytes,
            file.filename,
            len(file_bytes),
            doc_type_enum.value,     # pass validated doc_type
            user_id,                  # pass user_id for metadata
        )
        if not chunks:
            raise HTTPException(status_code=422, detail="No text could be extracted")

        # Embed (dense + sparse) → store in Qdrant + Supabase
        result = await asyncio.to_thread(
            process_upload,
            chunks,
            doc_id,
            file.filename,
            user_id,
            doc_type_enum.value,
        )

        return UploadResponse(
            doc_id     = result["doc_id"],
            doc_name   = result["doc_name"],
            doc_type   = result["doc_type"],
            num_chunks = result["num_chunks"],
            message    = (
                "Loaded from cache"
                if result["already_existed"]
                else f"Indexed {result['num_chunks']} chunks (type={doc_type_enum.value})"
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Upload failed for {file.filename}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


# ── GET /documents ────────────────────────────────────────────────────────────

@router.get("/documents", response_model=list[DocMeta])
async def list_documents(user_id: str = Depends(get_current_user_id)):
    """Return all documents the current user has uploaded."""
    docs = await asyncio.to_thread(get_user_documents, user_id)
    return docs


# ── DELETE /documents/{doc_id} ────────────────────────────────────────────────

@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Delete a document's embeddings and metadata completely."""
    # Verify ownership
    exists = await asyncio.to_thread(doc_exists_for_user, doc_id, user_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        await asyncio.to_thread(delete_document_full, doc_id, user_id)
        return {"message": "Document deleted", "doc_id": doc_id}
    except Exception as e:
        logger.exception(f"Delete failed for doc_id={doc_id}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


# ── POST /ask ─────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=AskResponse)
async def ask_question(
    request: AskRequest,
    user_id: str = Depends(get_current_user_id),
):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if not request.doc_ids:
        raise HTTPException(status_code=400, detail="At least one doc_id is required")

    # Security: verify all doc_ids belong to authenticated user
    user_docs = await asyncio.to_thread(get_user_documents, user_id)
    user_doc_ids = {d["doc_id"] for d in user_docs}
    unauthorized = [did for did in request.doc_ids if did not in user_doc_ids]
    if unauthorized:
        raise HTTPException(status_code=403, detail="Access denied to one or more documents")

    try:
        # run_rag now takes user_id for metadata-filtered hybrid search
        response = await asyncio.to_thread(run_rag, request, user_id)
        return response
    except Exception as e:
        logger.exception("RAG pipeline failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate answer: {str(e)}")


# ── GET /debug/qdrant — inspect vector store ─────────────────────────────────

@router.get("/debug/qdrant")
async def debug_qdrant():
    """Shows unified collection info: vector counts, sample data (dev only)."""
    from app.core.config import get_settings

    client   = get_qdrant_client()
    settings = get_settings()
    name     = settings.collection_name

    if not client.collection_exists(name):
        return {"collection": name, "exists": False, "count": 0}

    info  = client.get_collection(name)
    count = info.points_count or 0

    samples = []
    if count > 0:
        scroll = client.scroll(collection_name=name, limit=5, with_payload=True)
        for point in scroll[0]:
            p = point.payload or {}
            samples.append({
                "id":        str(point.id),
                "chunk_id":  p.get("chunk_id", ""),
                "doc_id":    p.get("doc_id", ""),
                "doc_type":  p.get("doc_type", ""),
                "user_id":   p.get("user_id", "")[:8] + "…",
                "page":      p.get("page_number"),
                "heading":   p.get("heading", ""),
                "text":      (p.get("text", "")[:120] + "…") if len(p.get("text", "")) > 120 else p.get("text", ""),
            })

    return {
        "collection": name,
        "exists":     True,
        "count":      count,
        "vectors":    {"dense": "384-dim COSINE", "sparse": "BM25 + IDF"},
        "samples":    samples,
    }
