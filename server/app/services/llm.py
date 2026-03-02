"""
LLM service — enterprise RAG pipeline using Google Gemini.

Flow:
  1. Query transformation — rewrite user question into standalone search query
  2. Hybrid retrieval  — dense + sparse search with RRF fusion (Top 15)
  3. Re-ranking        — cross-encoder scores and keeps Top 3
  4. Generation        — Gemini produces answer with structured citations
"""

import json
import logging
import re

import google.generativeai as genai

from app.core.config import get_settings
from app.models.schemas import AskRequest, AskResponse, Citation, ConversationTurn
from app.services.vector_store import hybrid_search
from app.services.reranker import Reranker

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

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
- Copy chunk_id values EXACTLY as they appear in the context — character for character.
- If the answer requires multiple points, include a citation for each point.
- If you cannot answer from the provided context, say so in the answer field and return an empty citations array.
- Keep answers clear, direct, and grounded in the document text.
- Do NOT include raw chunk text or chunk_ids in the answer — the answer should read as natural prose.
"""


# ── Query transformation ──────────────────────────────────────────────────────

REWRITE_PROMPT = """You are a search query optimizer. Given a conversation and the user's latest message, rewrite it as a single standalone search query that captures the full intent — including any context from the conversation history.

Rules:
- Output ONLY the rewritten query, nothing else.
- If the question is already standalone with no history, return it as-is.
- Remove pronouns that reference earlier messages (e.g., "it", "that", "they") and replace with specific terms.
- Keep the query concise (under 40 words).

Conversation history:
{history}

Latest message: {query}

Standalone search query:"""


def transform_query(raw_query: str, history: list[ConversationTurn] | None) -> str:
    """
    Use a fast cheap LLM call to rewrite the user's query into a
    standalone, highly specific search query.
    """
    if not history:
        return raw_query

    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)

    try:
        model = genai.GenerativeModel(model_name=settings.query_rewrite_model)
        history_text = "\n".join(
            f"  {t.role}: {t.content}" for t in (history or [])[-6:]
        )
        prompt = REWRITE_PROMPT.format(history=history_text, query=raw_query)
        response = model.generate_content(prompt)
        rewritten = response.text.strip()

        if rewritten and len(rewritten) < 500:
            logger.info(f"Query rewrite: '{raw_query[:60]}' → '{rewritten[:60]}'")
            return rewritten
        return raw_query
    except Exception as e:
        logger.warning(f"Query rewrite failed, using original: {e}")
        return raw_query


# ── Context building ──────────────────────────────────────────────────────────

def _build_context_block(reranked: list[tuple]) -> str:
    """
    Build the context block from reranked results.
    reranked: list of (ScoredPoint, cross_encoder_score) tuples.
    """
    lines = ["--- RETRIEVED CONTEXT (re-ranked, most relevant first) ---\n"]
    for i, (point, ce_score) in enumerate(reranked, 1):
        p = point.payload
        page_ref = f"page {p['page_number']}" if p.get("page_number") else "no page ref"
        heading  = f" | heading: {p['heading']}" if p.get("heading") else ""
        lines.append(
            f"[{i}] chunk_id: {p['chunk_id']}\n"
            f"    source: {p['doc_name']} ({page_ref}{heading})\n"
            f"    relevance_score: {ce_score:.3f}\n"
            f"    text: {p['text']}\n"
        )
    return "\n".join(lines)


def _build_context_block_from_points(points: list) -> str:
    """Fallback: build context from raw Qdrant ScoredPoints (no reranker)."""
    lines = ["--- RETRIEVED CONTEXT ---\n"]
    for i, point in enumerate(points, 1):
        p = point.payload
        page_ref = f"page {p['page_number']}" if p.get("page_number") else "no page ref"
        heading  = f" | heading: {p['heading']}" if p.get("heading") else ""
        lines.append(
            f"[{i}] chunk_id: {p['chunk_id']}\n"
            f"    source: {p['doc_name']} ({page_ref}{heading})\n"
            f"    text: {p['text']}\n"
        )
    return "\n".join(lines)


# ── Gemini chat helpers ───────────────────────────────────────────────────────

def _build_history_for_gemini(history: list[ConversationTurn]) -> list[dict]:
    gemini_history = []
    for turn in history:
        role = "user" if turn.role == "user" else "model"
        gemini_history.append({"role": role, "parts": [turn.content]})
    return gemini_history


def _extract_json(raw: str) -> dict | None:
    """Try multiple strategies to extract a JSON object from LLM response."""
    # Strategy 1: direct parse
    try:
        return json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    # Strategy 2: strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    # Strategy 3: regex for first JSON object
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    # Strategy 4: manual brace matching
    first = raw.find('{')
    last  = raw.rfind('}')
    if first != -1 and last > first:
        try:
            return json.loads(raw[first:last + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _parse_llm_response(raw: str, chunk_map: dict) -> tuple[str, list[Citation]]:
    """Parse Gemini's JSON response and map chunk_ids to full Citation objects."""
    data = _extract_json(raw)

    if not data or not isinstance(data, dict):
        logger.warning(f"Failed to extract JSON: {raw[:300]}")
        return raw, []

    answer        = data.get("answer", "")
    raw_citations = data.get("citations", [])

    if not answer:
        answer = raw

    citations = []
    for rc in raw_citations:
        cid   = rc.get("chunk_id", "").strip()
        chunk = chunk_map.get(cid)

        # Partial match fallback
        if not chunk:
            for key, val in chunk_map.items():
                if key in cid or cid in key:
                    chunk = val
                    logger.info(f"Partial match: '{cid}' → '{key}'")
                    break

        if not chunk:
            logger.warning(f"LLM cited unknown chunk_id: '{cid}'")
            continue

        citations.append(Citation(
            doc_name = chunk["doc_name"],
            doc_id   = chunk["doc_id"],
            chunk_id = cid,
            page     = chunk.get("page_number"),
            heading  = chunk.get("heading") or None,
            quote    = chunk["text"],
            score    = chunk.get("ce_score"),
        ))

    logger.info(f"Parsed {len(citations)} citations from LLM response")
    return answer, citations


# ── Main RAG pipeline ─────────────────────────────────────────────────────────

def run_rag(request: AskRequest, user_id: str) -> AskResponse:
    """
    Full pipeline:
      1. Query transformation (chat-aware rewrite)
      2. Hybrid retrieval   (dense + sparse, RRF fusion, metadata-filtered)
      3. Re-ranking         (cross-encoder, Top 3)
      4. LLM generation     (Gemini with forced JSON citations)
    """
    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)

    # ── 1. Query transformation ───────────────────────────────────────────
    search_query = transform_query(
        request.question,
        request.conversation_history,
    )

    # ── 2. Hybrid retrieval (Top 15) ─────────────────────────────────────
    raw_results = hybrid_search(
        query   = search_query,
        user_id = user_id,
        doc_ids = request.doc_ids,
        top_k   = settings.retrieval_top_k,
    )

    if not raw_results:
        return AskResponse(
            answer       = "I couldn't find relevant content in the uploaded documents to answer that question.",
            citations    = [],
            search_query = search_query,
        )

    logger.info(f"Retrieved {len(raw_results)} candidates for: {search_query[:80]}")

    # ── 3. Re-rank → Top 3 ──────────────────────────────────────────────
    try:
        reranked = Reranker.get().rerank(
            query   = request.question,       # original question for reranking
            results = raw_results,
            top_k   = settings.rerank_top_k,
        )
        context_block = _build_context_block(reranked)

        # Build chunk_map from reranked results
        chunk_map = {}
        for point, ce_score in reranked:
            p = point.payload
            cid = p["chunk_id"].strip()
            chunk_map[cid] = {**p, "ce_score": ce_score}

    except Exception as e:
        logger.warning(f"Reranker failed, using raw results: {e}")
        # Fallback: use top-3 from hybrid search
        reranked_points = raw_results[:settings.rerank_top_k]
        context_block = _build_context_block_from_points(reranked_points)
        chunk_map = {}
        for point in reranked_points:
            p = point.payload
            cid = p["chunk_id"].strip()
            chunk_map[cid] = {**p, "ce_score": None}

    # ── 4. Generate answer with Gemini ───────────────────────────────────
    model = genai.GenerativeModel(
        model_name         = settings.llm_model,
        system_instruction = SYSTEM_PROMPT,
        generation_config  = {"response_mime_type": "application/json"},
    )

    current_message = f"{context_block}\n\n--- QUESTION ---\n{request.question}"
    history = _build_history_for_gemini(request.conversation_history)
    chat    = model.start_chat(history=history)
    response = chat.send_message(current_message)

    raw_text = response.text
    logger.info(f"LLM response (first 300 chars): {raw_text[:300]}")

    # ── 5. Parse + map citations ─────────────────────────────────────────
    answer, citations = _parse_llm_response(raw_text, chunk_map)

    return AskResponse(
        answer       = answer,
        citations    = citations,
        search_query = search_query,
    )
