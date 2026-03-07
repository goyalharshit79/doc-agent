"""
Enterprise parsing pipeline — unstructured + adaptive chunking.

Flow:
  1. Parse any supported file into structured elements (unstructured library)
  2. Convert elements into clean Markdown (preserves tables, headers)
  3. Split Markdown into chunks using doc_type-aware strategy
  4. Attach strict metadata to every chunk:
       user_id, doc_id, doc_type, page_number, heading

Supported:  PDF (fast strategy — no OCR deps), DOCX, TXT, MD
"""

import hashlib
import logging
import re
from io import BytesIO

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_doc_id(filename: str, size: int) -> str:
    """Stable ID from filename + size — same file always gets same ID."""
    return hashlib.sha256(f"{filename}:{size}".encode()).hexdigest()[:16]


# ── Stage 1: Parse to Markdown elements ───────────────────────────────────────

_TEXT_EXTENSIONS = {".md", ".txt"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)")  # Markdown headings


def _parse_text_native(file_bytes: bytes, filename: str) -> list[dict]:
    """
    Lightweight parser for plain-text files (.md, .txt).
    Avoids unstructured entirely — just decode, split by lines, and
    detect Markdown headings natively. No external deps needed.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    parts = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            level = len(heading_match.group(1))
            parts.append({
                "text":       stripped,
                "page":       None,
                "category":   "Title" if level <= 2 else "Header",
                "is_heading": True,
                "is_table":   False,
            })
        elif stripped.startswith("- ") or stripped.startswith("* "):
            parts.append({
                "text":       stripped,
                "page":       None,
                "category":   "ListItem",
                "is_heading": False,
                "is_table":   False,
            })
        else:
            parts.append({
                "text":       stripped,
                "page":       None,
                "category":   "NarrativeText",
                "is_heading": False,
                "is_table":   False,
            })

    return parts


def _parse_to_elements(file_bytes: bytes, filename: str) -> list[dict]:
    """
    Parse any supported document into structured elements.
    For .md / .txt: use lightweight native parser (fast, no deps).
    For .pdf / .docx: use unstructured library.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # ── Native parser for text-based formats ────────────────────────────
    if ext in _TEXT_EXTENSIONS:
        logger.info(f"Using native text parser for {filename}")
        return _parse_text_native(file_bytes, filename)

    # ── Unstructured for PDF, DOCX ──────────────────────────────────────
    from unstructured.partition.auto import partition

    elements = partition(
        file=BytesIO(file_bytes),
        metadata_filename=filename,
        strategy="fast",           # no OCR / layout-model deps on Windows
    )

    parts = []
    for el in elements:
        page = getattr(el.metadata, "page_number", None)
        cat  = el.category  # Title, NarrativeText, Table, ListItem, Header, …

        # Convert to Markdown notation
        if cat == "Title":
            md = f"## {el.text}"
        elif cat == "Header":
            md = f"# {el.text}"
        elif cat == "Table":
            # Prefer HTML table repr (rendered by preview); fall back to plain
            html = getattr(el.metadata, "text_as_html", None)
            md = html if html else el.text
        elif cat == "ListItem":
            md = f"- {el.text}"
        else:
            md = el.text

        if not md or not md.strip():
            continue

        parts.append({
            "text":       md,
            "page":       page,
            "category":   cat,
            "is_heading": cat in ("Title", "Header"),
            "is_table":   cat == "Table",
        })

    return parts


# ── Stage 2: Adaptive chunking ───────────────────────────────────────────────

def _group_into_sections(parts: list[dict]) -> list[dict]:
    """
    Group elements by heading boundaries.
    Returns list of section dicts:
      { heading, page, texts: [(text, page, is_table), …] }
    """
    sections = []
    current = {"heading": None, "page": None, "texts": []}

    for p in parts:
        if p["is_heading"]:
            # Flush current section
            if current["texts"]:
                sections.append(current)
            current = {
                "heading": p["text"].lstrip("#").strip(),
                "page":    p["page"],
                "texts":   [],
            }
        else:
            if current["page"] is None and p["page"]:
                current["page"] = p["page"]
            current["texts"].append(
                (p["text"], p["page"], p.get("is_table", False))
            )

    if current["texts"]:
        sections.append(current)

    return sections


def _preprocess_contract(parts: list[dict]) -> list[dict]:
    """
    For contracts: detect numbered clauses / articles and promote them
    to heading boundaries so they never get split mid-clause.
    Patterns: "1.", "1.1", "Section 1", "Article II", "Clause 3.2"
    """
    CLAUSE_RE = re.compile(
        r"^(?:Section|Article|Clause|SECTION|ARTICLE|CLAUSE)?\s*"
        r"(?:\d+[\.\)]\d*[\.\)]?|[IVXLCDM]+[\.\)])\s",
        re.IGNORECASE,
    )
    processed = []
    for p in parts:
        if not p["is_heading"] and CLAUSE_RE.match(p["text"][:60]):
            processed.append({**p, "is_heading": True})
        else:
            processed.append(p)
    return processed


# Max words for a "short label" that should stay attached to a table
_TABLE_LABEL_MAX_WORDS = 40


def _chunk_sections(
    sections: list[dict],
    max_words: int,
    overlap_words: int,
    doc_type: str,
    doc_id: str,
    doc_name: str,
    user_id: str,
) -> list[dict]:
    """
    Chunk sections respecting word limits, with overlap for context continuity.

    Table-aware: tables are never split. If a table is encountered, any short
    preceding text (caption / label, ≤40 words) is kept with the table.

    For resumes: allow 150% overshoot to keep sections intact.
    """
    chunks = []
    counter = 0

    def _emit(text: str, page, heading):
        """Helper to create and append a chunk."""
        nonlocal counter
        if text.strip():
            chunks.append({
                "chunk_id":    f"{doc_id}_p{page or 0}_c{counter}",
                "text":        text,
                "doc_id":      doc_id,
                "doc_name":    doc_name,
                "doc_type":    doc_type,
                "user_id":     user_id,
                "page_number": page,
                "heading":     heading,
            })
            counter += 1

    for sec in sections:
        heading    = sec["heading"]
        chunk_page = sec["page"]

        # ── Resume heuristic: keep small sections whole ───────────────────
        if doc_type == "resume":
            combined = "\n\n".join(t for t, _, _tbl in sec["texts"])
            if len(combined.split()) <= int(max_words * 2.5):
                _emit(combined, chunk_page, heading)
                continue

        # ── Standard chunking with table-awareness ────────────────────────
        buffer_texts: list[str] = []
        buffer_words = 0

        for text, page, is_table in sec["texts"]:
            text_words = len(text.split())

            if is_table:
                # ── TABLE: treat as an atomic, unsplittable unit ──────────

                # Check if the last buffer item is a short label/caption
                # that should stay attached to this table for context
                label = ""
                if (buffer_texts
                        and len(buffer_texts[-1].split()) <= _TABLE_LABEL_MAX_WORDS):
                    label = buffer_texts.pop()
                    buffer_words -= len(label.split())

                # Flush any remaining pre-table buffer as its own chunk
                if buffer_texts:
                    chunk_text = "\n\n".join(buffer_texts)
                    _emit(chunk_text, chunk_page, heading)
                    buffer_texts = []
                    buffer_words = 0

                # Emit the table (with its label) as a single atomic chunk
                table_chunk = f"{label}\n\n{text}" if label else text
                if page:
                    chunk_page = page
                _emit(table_chunk, chunk_page, heading)

                # No overlap carry-over after a table — start fresh
                continue

            # ── Regular (non-table) element ───────────────────────────────
            if buffer_words + text_words > max_words and buffer_texts:
                # Flush current buffer as a chunk
                chunk_text = "\n\n".join(buffer_texts)
                _emit(chunk_text, chunk_page, heading)

                # Overlap: carry last N words into the next chunk
                all_words = chunk_text.split()
                if len(all_words) > overlap_words:
                    carry = " ".join(all_words[-overlap_words:])
                    buffer_texts = [carry]
                    buffer_words = overlap_words
                else:
                    buffer_texts = []
                    buffer_words = 0

            buffer_texts.append(text)
            buffer_words += text_words
            if page:
                chunk_page = page

        # Flush remainder
        if buffer_texts:
            chunk_text = "\n\n".join(buffer_texts)
            _emit(chunk_text, chunk_page, heading)

    return chunks


# ── Main entry point ──────────────────────────────────────────────────────────

def parse_document(
    file_bytes: bytes,
    filename: str,
    file_size: int,
    doc_type: str = "general",
    user_id: str = "",
) -> tuple[str, list[dict]]:
    """
    Full pipeline: file bytes → (doc_id, list[chunk_dict]).

    Every chunk dict contains:
      chunk_id, text, doc_id, doc_name, doc_type, user_id, page_number, heading
    """
    doc_id = make_doc_id(filename, file_size)
    settings = get_settings()

    # ── 1. Parse ──────────────────────────────────────────────────────────
    logger.info(f"Parsing {filename} (type={doc_type}, {file_size} bytes)")
    parts = _parse_to_elements(file_bytes, filename)

    if not parts:
        logger.warning(f"No content extracted from {filename}")
        return doc_id, []

    logger.info(f"Extracted {len(parts)} elements from {filename}")

    # ── 2. Doc-type preprocessing ─────────────────────────────────────────
    if doc_type == "contract":
        parts = _preprocess_contract(parts)

    # ── 3. Group into sections by heading ─────────────────────────────────
    sections = _group_into_sections(parts)

    # ── 4. Adaptive chunk ─────────────────────────────────────────────────
    cfg = settings.chunk_config.get(doc_type, settings.chunk_config["general"])
    chunks = _chunk_sections(
        sections      = sections,
        max_words     = cfg["size"],
        overlap_words = cfg["overlap"],
        doc_type      = doc_type,
        doc_id        = doc_id,
        doc_name      = filename,
        user_id       = user_id,
    )

    logger.info(
        f"Chunked {filename} → {len(chunks)} chunks "
        f"(strategy={doc_type}, max_words={cfg['size']}, overlap={cfg['overlap']})"
    )
    return doc_id, chunks
