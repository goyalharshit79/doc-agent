from enum import Enum
from pydantic import BaseModel
from typing import Optional


# ── Document Type ─────────────────────────────────────────────────────────────

class DocType(str, Enum):
    contract       = "contract"
    medical_report = "medical_report"
    book           = "book"
    resume         = "resume"
    general        = "general"


# ── Upload ────────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    doc_id: str
    doc_name: str
    doc_type: str
    num_chunks: int
    message: str


# ── Ask ───────────────────────────────────────────────────────────────────────

class ConversationTurn(BaseModel):
    role: str        # "user" | "assistant"
    content: str

class AskRequest(BaseModel):
    question: str
    doc_ids: list[str]                          # which docs to search across
    conversation_history: list[ConversationTurn] = []

class Citation(BaseModel):
    doc_name: str
    doc_id: str
    chunk_id: str
    page: Optional[int] = None
    heading: Optional[str] = None
    quote: str                                  # exact passage text
    score: Optional[float] = None               # reranker confidence

class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    search_query: Optional[str] = None          # transformed query (for debugging)


# ── Session ───────────────────────────────────────────────────────────────────

class DocMeta(BaseModel):
    doc_id: str
    doc_name: str
    doc_type: str
    num_chunks: int
