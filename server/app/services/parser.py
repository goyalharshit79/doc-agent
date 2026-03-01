"""
Parsing pipeline — extracts structured chunks from PDF, DOCX, and TXT files.

Every chunk carries:
  chunk_id        : "<doc_id>_p<page>_c<index>"
  doc_id          : hash identifier for the document
  doc_name        : original filename
  page            : page number (1-indexed, None for TXT)
  heading         : nearest heading above this chunk (if any)
  paragraph_index : position within the page/section
  text            : the actual text content
"""

import hashlib
import re
from typing import BinaryIO


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_doc_id(filename: str, size: int) -> str:
    """Stable ID from filename + size — same file always gets same ID."""
    return hashlib.sha256(f"{filename}:{size}".encode()).hexdigest()[:16]


def _split_into_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    """
    Split text into overlapping chunks by word count.
    Overlap is in words to avoid cutting context at boundaries.
    """
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


# ── PDF ────────────────────────────────────────────────────────────────────────

def parse_pdf(file_bytes: bytes, doc_id: str, doc_name: str) -> list[dict]:
    import pdfplumber

    chunks = []
    chunk_counter = 0

    with pdfplumber.open(file_bytes) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            lines = text.split("\n")
            current_heading = None
            paragraph_buffer = []
            para_index = 0

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    # flush buffer on blank line
                    if paragraph_buffer:
                        para_text = " ".join(paragraph_buffer)
                        for sub in _chunk_text(para_text):
                            chunks.append({
                                "chunk_id":        f"{doc_id}_p{page_num}_c{chunk_counter}",
                                "doc_id":          doc_id,
                                "doc_name":        doc_name,
                                "page":            page_num,
                                "heading":         current_heading,
                                "paragraph_index": para_index,
                                "text":            sub,
                            })
                            chunk_counter += 1
                        para_index += 1
                        paragraph_buffer = []
                    continue

                # Heuristic: short ALL-CAPS or title-case short lines are headings
                if len(stripped) < 80 and (stripped.isupper() or re.match(r'^[A-Z][^a-z]{0,5}', stripped)):
                    if paragraph_buffer:
                        para_text = " ".join(paragraph_buffer)
                        for sub in _chunk_text(para_text):
                            chunks.append({
                                "chunk_id":        f"{doc_id}_p{page_num}_c{chunk_counter}",
                                "doc_id":          doc_id,
                                "doc_name":        doc_name,
                                "page":            page_num,
                                "heading":         current_heading,
                                "paragraph_index": para_index,
                                "text":            sub,
                            })
                            chunk_counter += 1
                        para_index += 1
                        paragraph_buffer = []
                    current_heading = stripped
                else:
                    paragraph_buffer.append(stripped)

            # flush remaining buffer
            if paragraph_buffer:
                para_text = " ".join(paragraph_buffer)
                for sub in _chunk_text(para_text):
                    chunks.append({
                        "chunk_id":        f"{doc_id}_p{page_num}_c{chunk_counter}",
                        "doc_id":          doc_id,
                        "doc_name":        doc_name,
                        "page":            page_num,
                        "heading":         current_heading,
                        "paragraph_index": para_index,
                        "text":            sub,
                    })
                    chunk_counter += 1

    return chunks


# ── DOCX ───────────────────────────────────────────────────────────────────────

def parse_docx(file_bytes: bytes, doc_id: str, doc_name: str) -> list[dict]:
    import io
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(io.BytesIO(file_bytes))
    chunks = []
    chunk_counter = 0
    current_heading = None
    para_index = 0
    # DOCX has no real page numbers without rendering — we use section index instead
    section_index = 0

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style = para.style.name or ""
        is_heading = style.lower().startswith("heading")

        if is_heading:
            current_heading = text
            section_index += 1
            para_index = 0
            continue

        for sub in _chunk_text(text):
            chunks.append({
                "chunk_id":        f"{doc_id}_s{section_index}_c{chunk_counter}",
                "doc_id":          doc_id,
                "doc_name":        doc_name,
                "page":            None,          # DOCX: no reliable page number
                "heading":         current_heading,
                "paragraph_index": para_index,
                "text":            sub,
            })
            chunk_counter += 1
        para_index += 1

    return chunks


# ── TXT / MD ───────────────────────────────────────────────────────────────────

def parse_text(file_bytes: bytes, doc_id: str, doc_name: str) -> list[dict]:
    text = file_bytes.decode("utf-8", errors="replace")
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    chunk_counter = 0
    current_heading = None

    for para_index, para in enumerate(paragraphs):
        # Markdown headings
        if para.startswith("#"):
            current_heading = para.lstrip("#").strip()
            continue

        for sub in _chunk_text(para):
            chunks.append({
                "chunk_id":        f"{doc_id}_c{chunk_counter}",
                "doc_id":          doc_id,
                "doc_name":        doc_name,
                "page":            None,
                "heading":         current_heading,
                "paragraph_index": para_index,
                "text":            sub,
            })
            chunk_counter += 1

    return chunks


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def parse_document(file_bytes: bytes, filename: str, file_size: int) -> tuple[str, list[dict]]:
    """
    Entry point. Returns (doc_id, chunks).
    """
    doc_id = make_doc_id(filename, file_size)
    ext = filename.rsplit(".", 1)[-1].lower()

    if ext == "pdf":
        import io
        chunks = parse_pdf(io.BytesIO(file_bytes), doc_id, filename)
    elif ext == "docx":
        chunks = parse_docx(file_bytes, doc_id, filename)
    elif ext in ("txt", "md"):
        chunks = parse_text(file_bytes, doc_id, filename)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    return doc_id, chunks
