"""
LLM service — RAG pipeline using Google Gemini.

Flow:
  1. Receive question + doc_ids + conversation_history
  2. Run similarity search across doc_ids
  3. Build prompt with retrieved chunks (each tagged with chunk_id)
  4. Call Gemini — enforced to respond ONLY in citation JSON
  5. Parse response, map chunk_ids back to full metadata
  6. Return structured AskResponse
"""

import json
import logging
import re

import google.generativeai as genai

from app.core.config import get_settings
from app.models.schemas import AskRequest, AskResponse, Citation, ConversationTurn
from app.services.vector_store import similarity_search

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are DocAgent, a precise document analysis assistant.

You MUST respond ONLY with a valid JSON object in this exact format — no preamble, no explanation outside the JSON:

{
  "answer": "Your full answer here in clear prose.",
  "citations": [
    {
      "chunk_id": "the exact chunk_id string from the context",
      "relevance": "one sentence explaining why this chunk supports the answer"
    }
  ]
}

Rules:
- NEVER make a claim without a citation.
- NEVER cite a chunk_id that was not in the provided context.
- If the answer requires multiple points, include a citation for each point.
- If you cannot answer from the provided context, say so in the answer field and return an empty citations array.
- Keep answers clear, direct, and grounded in the document text.
"""


def _build_context_block(chunks: list[dict]) -> str:
    lines = ["--- RETRIEVED CONTEXT ---\n"]
    for i, chunk in enumerate(chunks, 1):
        page_ref = f"page {chunk['page']}" if chunk.get("page") else "no page ref"
        heading  = f" | heading: {chunk['heading']}" if chunk.get("heading") else ""
        lines.append(
            f"[{i}] chunk_id: {chunk['chunk_id']}\n"
            f"    source: {chunk['doc_name']} ({page_ref}{heading})\n"
            f"    text: {chunk['text']}\n"
        )
    return "\n".join(lines)


def _build_history_for_gemini(history: list[ConversationTurn]) -> list[dict]:
    """Convert our ConversationTurn list to Gemini's history format."""
    gemini_history = []
    for turn in history:
        role = "user" if turn.role == "user" else "model"
        gemini_history.append({
            "role": role,
            "parts": [turn.content]
        })
    return gemini_history


def _parse_llm_response(raw: str, chunks: list[dict]) -> tuple[str, list[Citation]]:
    cleaned = re.sub(r"```json|```", "", raw).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"LLM returned non-JSON: {raw[:200]}")
        return raw, []

    answer = data.get("answer", "")
    raw_citations = data.get("citations", [])

    chunk_map = {c["chunk_id"]: c for c in chunks}

    citations = []
    for rc in raw_citations:
        cid = rc.get("chunk_id", "")
        chunk = chunk_map.get(cid)
        if not chunk:
            logger.warning(f"LLM cited unknown chunk_id: {cid}")
            continue
        citations.append(Citation(
            doc_name = chunk["doc_name"],
            doc_id   = chunk["doc_id"],
            chunk_id = cid,
            page     = chunk.get("page"),
            heading  = chunk.get("heading"),
            quote    = chunk["text"],
        ))

    return answer, citations


def run_rag(request: AskRequest) -> AskResponse:
    settings = get_settings()

    # 1. Retrieve relevant chunks
    chunks = similarity_search(
        query   = request.question,
        doc_ids = request.doc_ids,
        top_k   = settings.top_k_chunks,
    )

    if not chunks:
        return AskResponse(
            answer    = "I couldn't find relevant content in the uploaded documents to answer that question.",
            citations = [],
        )

    # 2. Configure Gemini
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name     = settings.llm_model,
        system_instruction = SYSTEM_PROMPT,
    )

    # 3. Build context + current question
    context_block = _build_context_block(chunks)
    current_message = f"{context_block}\n\n--- QUESTION ---\n{request.question}"

    # 4. Start chat with history, send current message
    history = _build_history_for_gemini(request.conversation_history)
    chat = model.start_chat(history=history)
    response = chat.send_message(current_message)

    raw_text = response.text

    # 5. Parse + map citations
    answer, citations = _parse_llm_response(raw_text, chunks)

    return AskResponse(answer=answer, citations=citations)
