import asyncio
import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.auth import get_current_user_id
from app.models.schemas import AskRequest, AskResponse, DocMeta, DocType, UploadResponse
from app.services.parser import make_doc_id, parse_document
from app.services.vector_store import (
    get_user_documents,
    process_upload,
    delete_document_full,
    doc_exists_for_user,
    get_doc_meta_by_id,
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

    # ── Fast path: check if this exact doc already exists (skip parsing) ──
    doc_id = make_doc_id(file.filename, len(file_bytes))
    cached = await asyncio.to_thread(get_doc_meta_by_id, doc_id, user_id)
    if cached:
        logger.info(f"Fast cache hit for doc_id={doc_id} — skipping parse & embed")
        return UploadResponse(
            doc_id     = cached["doc_id"],
            doc_name   = cached["doc_name"],
            doc_type   = cached["doc_type"],
            num_chunks = cached["num_chunks"],
            message    = "Loaded from cache",
        )

    try:
        t_upload_start = time.perf_counter()

        # Parse (unstructured → Markdown → adaptive chunking)
        t0 = time.perf_counter()
        doc_id, chunks = await asyncio.to_thread(
            parse_document,
            file_bytes,
            file.filename,
            len(file_bytes),
            doc_type_enum.value,     # pass validated doc_type
            user_id,                  # pass user_id for metadata
        )
        logger.info(f"⏱  PARSE       {time.perf_counter() - t0:.2f}s  ({file.filename} → {len(chunks)} chunks)")

        if not chunks:
            raise HTTPException(status_code=422, detail="No text could be extracted")

        # Embed (dense + sparse) → store in Vertex AI + Supabase
        t0 = time.perf_counter()
        result = await asyncio.to_thread(
            process_upload,
            chunks,
            doc_id,
            file.filename,
            user_id,
            doc_type_enum.value,
        )
        logger.info(f"⏱  EMBED+STORE {time.perf_counter() - t0:.2f}s  ({result['num_chunks']} chunks)")

        t_total = time.perf_counter() - t_upload_start
        logger.info(f"⏱  UPLOAD TOTAL {t_total:.2f}s  ({file.filename})")

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
        t0 = time.perf_counter()
        # run_rag now takes user_id for metadata-filtered hybrid search
        response = await asyncio.to_thread(run_rag, request, user_id)
        logger.info(f"⏱  ASK TOTAL   {time.perf_counter() - t0:.2f}s  (question: {request.question[:60]})")
        return response
    except Exception as e:
        logger.exception("RAG pipeline failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate answer: {str(e)}")



