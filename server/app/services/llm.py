"""
LLM service — enterprise RAG pipeline using Google Gemini.

Flow:
  1. Query transformation — rewrite user question into standalone search query
  2. Hybrid retrieval  — dense + sparse search with RRF fusion (Top 15)
  3. Re-ranking        — cross-encoder scores and keeps Top 5
  4. Generation        — Gemini produces answer with structured citations
"""

import json
import logging
import re
import time

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.core.retry import gcp_retry
from app.models.schemas import AskRequest, AskResponse, Citation, ConversationTurn
from app.services.vector_store import hybrid_search
from app.services.reranker import Reranker

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are **DocAgent**, a sharp document analysis assistant.

Your job is to analyze the provided context chunks and give a **clear, focused, and well-structured** answer. Be informative but concise — no essays.

---

## RESPONSE FORMAT

You MUST respond ONLY with a valid JSON object — no text before or after it. Use this exact schema:

{
  "answer": "Your answer in Markdown (see formatting rules below).",
  "citations": [
    {
      "chunk_id": "the exact chunk_id string from the context",
      "relevance": "one sentence explaining why this chunk supports the answer"
    }
  ]
}

---

## REASONING INSTRUCTIONS

1. **Read all provided context chunks carefully** before composing your answer.
2. **Connect information** across chunks — identify patterns and reconcile contradictions.
3. **You may use your own knowledge** for definitions, terminology, or broader context. Any information NOT from the provided chunks MUST be labeled **"⚡ Beyond Document:"**.
4. **If you truly cannot answer** from the provided context, say so clearly and return an empty citations array.

---

## FORMATTING RULES (for the "answer" field)

Write in **clean Markdown** — prioritize readability and brevity:

- **Favor bullet points and short paragraphs** over long prose. Get the information across efficiently.
- Use **bold** for key terms, names, dates, amounts, and critical points.
- Use **## headings** only when the answer has 2+ distinct sections. Don't over-structure short answers.
- Use **tables** for comparative or numerical data.
- Use **blockquotes** (`>`) sparingly for significant direct quotes from the document.
- **Be concise**: answer the question directly, then add relevant detail. Don't repeat yourself or overexplain.
- For simple questions, a few sentences or bullet points is enough. Scale up only when the question demands it.

### CRITICAL — NEVER include these in the answer:
- **chunk_id strings** (e.g., "35cb0fcdd1e52656_p50_c48") — NEVER. These go ONLY in the citations array.
- Raw chunk text dumps — paraphrase or quote briefly instead.
- Internal metadata like page numbers, scores, or source references — the UI handles citation display separately.

The answer must read as polished, natural text with zero technical artifacts.

---

## CITATION RULES

- Every factual claim from the context MUST have at least one citation in the citations array.
- **Only cite chunk_ids that exist in the provided context** — never invent or guess.
- Copy chunk_id values **exactly** as they appear — character for character.
- Citations go ONLY in the `citations` array — **NEVER embed chunk_ids in the answer text**.
- Content labeled **"⚡ Beyond Document:"** does NOT need a citation.
"""


# ── Query transformation ──────────────────────────────────────────────────────

REWRITE_PROMPT = """You are a search query optimizer for a document Q&A system. Clean up and improve the user's latest message into the best possible search query.

Your tasks (apply ALL that are relevant):
1. **Fix typos and spelling** — correct any misspelled words.
2. **Fix grammar** — rephrase broken grammar into clean, natural language.
3. **Resolve references** — replace pronouns like "it", "that", "they", "this" with the specific terms they refer to from the conversation history.
4. **Expand abbreviations** — if the user uses shorthand or acronyms that are clear from context, expand them.
5. **Keep the meaning identical** — do NOT add intent, assumptions, or scope that the user did not express. Only clean up what's there.

Rules:
- Output ONLY the rewritten query, nothing else.
- If the query is already clean and standalone, return it as-is.
- Keep the query concise (under 40 words).
- Do NOT answer the question — just rewrite it.

{history_block}Latest message: {query}

Rewritten query:"""


def transform_query(raw_query: str, history: list[ConversationTurn] | None) -> str:
    """
    Use a fast cheap LLM call to rewrite the user's query —
    fix spelling/grammar, resolve pronouns from chat history,
    and produce a clean standalone search query.
    """

    settings = get_settings()

    try:
        client = genai.Client(
            vertexai=True,
            project=settings.gcp_project,
            location=settings.gcp_location
        )

        # Build optional history block
        if history:
            history_lines = "\n".join(
                f"  {t.role}: {t.content}" for t in history[-6:]
            )
            history_block = f"Conversation history:\n{history_lines}\n\n"
        else:
            history_block = ""

        prompt = REWRITE_PROMPT.format(history_block=history_block, query=raw_query)

        @gcp_retry
        def _rewrite_query(c, mdl, p):
            return c.models.generate_content(model=mdl, contents=p)

        response = _rewrite_query(client, settings.query_rewrite_model, prompt)
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


# ── Response parsing helpers ──────────────────────────────────────────────────

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

    # Safety net: strip any chunk_id strings that leaked into the answer text.
    # Pattern: hex{16}_p{digits}_c{digits}  (e.g. "35cb0fcdd1e52656_p50_c48")
    answer = re.sub(r'\s*\(?[0-9a-f]{8,}_p\d+_c\d+\)?\s*', ' ', answer).strip()

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
      3. Re-ranking         (cross-encoder, Top 5)
      4. LLM generation     (Gemini with forced JSON citations)
    """
    settings = get_settings()
    t_pipeline_start = time.perf_counter()

    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location
    )

    # ── 1. Query transformation ───────────────────────────────────────────
    t0 = time.perf_counter()
    search_query = transform_query(
        request.question,
        request.conversation_history,
    )
    logger.info(f"⏱  QUERY REWRITE  {time.perf_counter() - t0:.2f}s")

    # ── 2. Hybrid retrieval (Top 15) ─────────────────────────────────────
    t0 = time.perf_counter()
    raw_results = hybrid_search(
        query   = search_query,
        user_id = user_id,
        doc_ids = request.doc_ids,
        top_k   = settings.retrieval_top_k,
    )
    logger.info(f"⏱  RETRIEVAL      {time.perf_counter() - t0:.2f}s  ({len(raw_results)} candidates)")

    if not raw_results:
        return AskResponse(
            answer       = "I couldn't find relevant content in the uploaded documents to answer that question.",
            citations    = [],
            search_query = search_query,
        )

    logger.info(f"Retrieved {len(raw_results)} candidates for: {search_query[:80]}")

    # ── 3. Re-rank → Top 3 ──────────────────────────────────────────────
    t0 = time.perf_counter()
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
    logger.info(f"⏱  RERANK         {time.perf_counter() - t0:.2f}s  ({len(chunk_map)} kept)")

    # ── 4. Generate answer with Gemini ───────────────────────────────────

    # Build a single prompt with conversation context + retrieved chunks + question.
    # This avoids the broken chat history replay (which made real API calls per message).
    history_block = ""
    if request.conversation_history:
        history_lines = []
        for turn in request.conversation_history[-6:]:
            role_label = "User" if turn.role == "user" else "Assistant"
            history_lines.append(f"{role_label}: {turn.content}")
        history_block = (
            "--- CONVERSATION HISTORY (for context) ---\n"
            + "\n".join(history_lines)
            + "\n\n"
        )

    full_prompt = (
        f"{history_block}"
        f"{context_block}\n\n"
        f"--- QUESTION ---\n{request.question}"
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    pre_gen = time.perf_counter() - t_pipeline_start
    logger.info(f"⏱  PRE-GEN OVERHEAD {pre_gen:.2f}s  (rewrite + retrieval + rerank — TTFT floor)")

    t0 = time.perf_counter()

    @gcp_retry
    def _generate_answer(c, mdl, prompt, cfg):
        return c.models.generate_content(model=mdl, contents=prompt, config=cfg)

    response = _generate_answer(client, settings.llm_model, full_prompt, config)

    raw_text = response.text
    t_gen = time.perf_counter() - t0
    logger.info(f"⏱  LLM GENERATION  {t_gen:.2f}s  ({settings.llm_model})")
    logger.info(f"LLM response (first 300 chars): {raw_text[:300]}")

    # ── 5. Parse + map citations ─────────────────────────────────────────
    t0 = time.perf_counter()
    answer, citations = _parse_llm_response(raw_text, chunk_map)
    logger.info(f"⏱  PARSE RESPONSE  {time.perf_counter() - t0:.2f}s  ({len(citations)} citations)")

    t_total = time.perf_counter() - t_pipeline_start
    logger.info(
        f"⏱  TTFT (effective) {t_total:.2f}s  "
        f"(pre-gen={pre_gen:.2f}s + generation={t_gen:.2f}s) — no streaming"
    )

    return AskResponse(
        answer       = answer,
        citations    = citations,
        search_query = search_query,
    )
