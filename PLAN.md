# Enterprise RAG Pipeline — Implementation Plan

## Architecture Overview

```
UPLOAD FLOW (Phase 1):
  File + doc_type ──► unstructured partition() ──► Markdown elements
       ──► Adaptive Chunker (by doc_type) ──► Chunks with strict metadata
       ──► FastEmbed (dense BGE + sparse BM25) ──► Qdrant single collection

QUERY FLOW (Phase 2):
  Raw query + history ──► Gemini query rewrite ──► standalone search query
       ──► Qdrant hybrid search (dense + sparse RRF fusion + metadata filter)
       ──► Top 15 results ──► Cross-Encoder re-rank ──► Top 3 chunks
       ──► Gemini generation with citations ──► Response
```

## Decisions (from user)

| Decision | Choice |
|----------|--------|
| Parser | `unstructured` (fast strategy, no OCR deps needed) |
| Embeddings | FastEmbed — free, local (dense: BGE-small-en, sparse: BM25) |
| doc_type | User selects from dropdown on upload |
| Collection | Single unified `documents` collection with payload indexes |

---

## Step 1 — Dependencies (`server/requirements.txt`)

**Remove:** `pdfplumber`, `sentence-transformers`
**Add:**
- `unstructured[pdf,docx]==0.16.11` — document parsing (uses pdfminer + python-docx internally)
- `fastembed==0.4.1` — dense + sparse embedding generation
- `onnxruntime==1.19.2` — required by fastembed for model inference

**Keep:** `qdrant-client`, `google-generativeai`, `supabase`, `fastapi`, `uvicorn`, `python-multipart`, `pydantic`, `pydantic-settings`, `python-dotenv`, `httpx`, `passlib[bcrypt]`, `python-docx` (needed by unstructured)

**Note:** `sentence-transformers` is still needed for the CrossEncoder re-ranker. Keep it but we stop using SentenceTransformer for embeddings (FastEmbed replaces it).

---

## Step 2 — Config (`server/app/core/config.py`)

Add new settings:
```python
# Collection
collection_name: str = "documents"

# FastEmbed models
dense_model: str = "BAAI/bge-small-en-v1.5"      # 384-dim
sparse_model: str = "Qdrant/bm25"                  # BM25 sparse

# Re-ranker
reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Retrieval
retrieval_top_k: int = 15    # hybrid search returns 15
rerank_top_k: int = 3        # re-ranker keeps top 3

# Adaptive chunk sizes (words) by doc_type
chunk_config: dict = {
    "contract":       {"size": 600, "overlap": 100},
    "medical_report": {"size": 500, "overlap": 80},
    "book":           {"size": 800, "overlap": 150},
    "resume":         {"size": 300, "overlap": 50},
    "general":        {"size": 500, "overlap": 80},
}
```

---

## Step 3 — Schemas (`server/app/models/schemas.py`)

### Add `DocType` enum:
```python
class DocType(str, Enum):
    contract = "contract"
    medical_report = "medical_report"
    book = "book"
    resume = "resume"
    general = "general"
```

### Update `UploadResponse`:
- Add `doc_type: str` field

### Update `DocMeta`:
- Add `doc_type: str` field

### Update `Citation`:
- Add `score: float | None = None` field (for reranker transparency)

---

## Step 4 — Parser (`server/app/services/parser.py`) — FULL REWRITE

### 4a. Intelligent Parsing with `unstructured`

Replace pdfplumber/python-docx with:
```python
from unstructured.partition.auto import partition

def parse_to_markdown(file_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Parse any supported file into clean Markdown + page metadata."""
    elements = partition(file=BytesIO(file_bytes), metadata_filename=filename, strategy="fast")

    markdown_parts = []
    page_map = {}  # line_index -> page_number

    for el in elements:
        page = getattr(el.metadata, 'page_number', None)
        if el.category == "Title":
            markdown_parts.append(f"## {el.text}")
        elif el.category == "Header":
            markdown_parts.append(f"# {el.text}")
        elif el.category == "Table":
            html = getattr(el.metadata, 'text_as_html', None)
            markdown_parts.append(html or el.text)
        elif el.category == "ListItem":
            markdown_parts.append(f"- {el.text}")
        else:
            markdown_parts.append(el.text)
        page_map[len(markdown_parts) - 1] = page

    return "\n\n".join(markdown_parts), page_map
```

### 4b. Adaptive Chunking by doc_type

Markdown-aware splitter that:
1. **First pass**: Split on `## ` and `# ` headers (section boundaries)
2. **Second pass**: If any section exceeds `chunk_size`, split on `\n\n` (paragraphs)
3. **Third pass**: If still too large, split by sentences with overlap
4. Chunk sizes come from `config.chunk_config[doc_type]`

Special behaviors by doc_type:
- **Contract**: Detect numbered clauses (e.g., "1.1", "Section 3"). Never split mid-clause.
- **Resume**: Try to keep entire sections (Education, Experience) as single chunks.
- **Book**: Larger chunks with generous overlap for narrative continuity.
- **Medical Report**: Preserve complete paragraphs within findings/diagnosis sections.

### 4c. Strict metadata on every chunk

Every chunk dict MUST contain:
```python
{
    "chunk_id": f"{doc_id}_p{page}_c{counter}",
    "text": "...",
    "doc_id": doc_id,
    "doc_name": filename,
    "doc_type": doc_type,       # NEW — from user selection
    "user_id": user_id,         # NEW — from auth
    "page_number": int | None,  # from unstructured metadata
    "heading": str | None,      # nearest header above chunk
}
```

### 4d. Main entry point
```python
def parse_document(file_bytes, filename, file_size, doc_type, user_id) -> tuple[str, list[dict]]:
    doc_id = make_doc_id(filename, file_size)
    markdown, page_map = parse_to_markdown(file_bytes, filename)
    chunks = adaptive_chunk(markdown, page_map, doc_id, filename, doc_type, user_id)
    return doc_id, chunks
```

---

## Step 5 — Embeddings (`server/app/services/embeddings.py`) — NEW FILE

Encapsulates all embedding logic:

```python
from fastembed import TextEmbedding, SparseTextEmbedding

class EmbeddingService:
    _instance = None

    def __init__(self):
        self.dense_model = TextEmbedding("BAAI/bge-small-en-v1.5")    # 384-dim
        self.sparse_model = SparseTextEmbedding("Qdrant/bm25")        # BM25

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def encode_dense(self, texts: list[str]) -> list[list[float]]:
        return list(self.dense_model.embed(texts))

    def encode_sparse(self, texts: list[str]) -> list[SparseEmbedding]:
        return list(self.sparse_model.embed(texts))

    def encode_query_dense(self, query: str) -> list[float]:
        return list(self.dense_model.query_embed(query))[0]

    def encode_query_sparse(self, query: str) -> SparseEmbedding:
        return list(self.sparse_model.query_embed(query))[0]
```

---

## Step 6 — Vector Store (`server/app/services/vector_store.py`) — FULL REWRITE

### 6a. Single collection with named vectors

```python
COLLECTION = "documents"

def ensure_collection():
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config={
                "dense": models.VectorParams(size=384, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )
        # Payload indexes for filtered search
        client.create_payload_index(COLLECTION, "user_id", models.PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION, "doc_id", models.PayloadSchemaType.KEYWORD)
        client.create_payload_index(COLLECTION, "doc_type", models.PayloadSchemaType.KEYWORD)
```

### 6b. Upsert with dual vectors

```python
def embed_and_store(chunks: list[dict]):
    texts = [c["text"] for c in chunks]
    dense_vectors = embedding_svc.encode_dense(texts)
    sparse_vectors = embedding_svc.encode_sparse(texts)

    points = []
    for i, chunk in enumerate(chunks):
        point_id = str(uuid5(NAMESPACE_DNS, chunk["chunk_id"]))
        points.append(models.PointStruct(
            id=point_id,
            vector={
                "dense": dense_vectors[i].tolist(),
                "sparse": models.SparseVector(
                    indices=sparse_vectors[i].indices.tolist(),
                    values=sparse_vectors[i].values.tolist(),
                ),
            },
            payload={
                "chunk_id":    chunk["chunk_id"],
                "text":        chunk["text"],
                "doc_id":      chunk["doc_id"],
                "doc_name":    chunk["doc_name"],
                "doc_type":    chunk["doc_type"],
                "user_id":     chunk["user_id"],
                "page_number": chunk["page_number"],
                "heading":     chunk["heading"],
            },
        ))
    client.upsert(COLLECTION, points, wait=True)
```

### 6c. Hybrid search with RRF fusion + strict metadata filtering

```python
def hybrid_search(query: str, user_id: str, doc_ids: list[str], top_k: int = 15):
    dense_qv = embedding_svc.encode_query_dense(query)
    sparse_qv = embedding_svc.encode_query_sparse(query)

    # Strict metadata filter — MUST match user_id AND doc_id(s)
    must_filter = models.Filter(must=[
        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
        models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids)),
    ])

    results = client.query_points(
        collection_name=COLLECTION,
        prefetch=[
            models.Prefetch(query=dense_qv, using="dense", limit=20, filter=must_filter),
            models.Prefetch(
                query=models.SparseVector(
                    indices=sparse_qv.indices.tolist(),
                    values=sparse_qv.values.tolist(),
                ),
                using="sparse",
                limit=20,
                filter=must_filter,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )
    return results.points
```

### 6d. Keyword search function

```python
def keyword_search(query: str, user_id: str, doc_ids: list[str], top_k: int = 10):
    """Pure sparse/keyword search for exact term matching."""
    sparse_qv = embedding_svc.encode_query_sparse(query)
    must_filter = models.Filter(must=[
        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
        models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids)),
    ])

    results = client.query_points(
        collection_name=COLLECTION,
        query=models.SparseVector(
            indices=sparse_qv.indices.tolist(),
            values=sparse_qv.values.tolist(),
        ),
        using="sparse",
        query_filter=must_filter,
        limit=top_k,
        with_payload=True,
    )
    return results.points
```

### 6e. Delete document (for cleanup)

```python
def delete_document_vectors(doc_id: str, user_id: str):
    """Remove all vectors for a specific document."""
    client.delete(
        collection_name=COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            ])
        ),
    )
```

### 6f. Supabase integration stays
- `save_doc_meta` — add `doc_type` column
- `get_user_documents` — include `doc_type` in response
- `doc_exists_for_user` — unchanged

---

## Step 7 — Re-ranker (`server/app/services/reranker.py`) — NEW FILE

```python
from sentence_transformers import CrossEncoder

class Reranker:
    _instance = None

    def __init__(self):
        self.model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def rerank(self, query: str, results: list, top_k: int = 3) -> list:
        if not results:
            return []
        pairs = [(query, r.payload["text"]) for r in results]
        scores = self.model.predict(pairs)

        scored = list(zip(results, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]  # Returns list of (point, score) tuples
```

---

## Step 8 — LLM Service (`server/app/services/llm.py`) — SIGNIFICANT UPDATE

### 8a. Query Transformation (NEW)

```python
REWRITE_PROMPT = """Rewrite the user's latest message as a single standalone search query.
Use the conversation history for context. Output ONLY the rewritten query, nothing else.

Conversation history:
{history}

Latest message: {query}

Standalone search query:"""

def transform_query(raw_query: str, history: list) -> str:
    if not history:
        return raw_query
    model = genai.GenerativeModel("gemini-2.0-flash-lite")
    history_text = "\n".join(f"{t.role}: {t.content}" for t in history[-6:])
    prompt = REWRITE_PROMPT.format(history=history_text, query=raw_query)
    resp = model.generate_content(prompt)
    return resp.text.strip() or raw_query
```

### 8b. Updated `run_rag()` pipeline

```python
async def run_rag(request, user_id):
    # 1. Query transformation
    search_query = transform_query(request.question, request.conversation_history or [])

    # 2. Hybrid retrieval (Top 15, metadata-filtered)
    raw_results = hybrid_search(search_query, user_id, request.doc_ids, top_k=15)

    # 3. Re-rank → Top 3
    reranked = Reranker.get().rerank(request.question, raw_results, top_k=3)

    # 4. Build context from top 3 chunks
    context = build_context(reranked)

    # 5. Generate answer with Gemini (existing logic, updated context)
    answer, citations = generate_answer(request.question, context, request.conversation_history)

    return AskResponse(answer=answer, citations=citations)
```

### 8c. System prompt stays largely the same
- Same JSON-only enforcement
- Same citation format
- Updated to mention re-ranked context quality

---

## Step 9 — Routes (`server/app/api/routes.py`)

### Upload endpoint changes:
```python
@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    doc_type: str = Form("general"),      # NEW — from dropdown
    user_id: str = Depends(get_current_user_id),
):
    # Validate doc_type against DocType enum
    # Pass doc_type + user_id to parser
    doc_id, chunks = parse_document(file_bytes, filename, file_size, doc_type, user_id)
    result = await process_upload(chunks, doc_id, filename, user_id, doc_type)
    return UploadResponse(...)
```

### Ask endpoint changes:
```python
@router.post("/ask")
async def ask(body: AskRequest, user_id: str = Depends(get_current_user_id)):
    # Same security check (verify doc_ids belong to user)
    # Pass user_id to run_rag for metadata filtering
    result = await run_rag(body, user_id)
    return result
```

### Debug endpoint:
- Update to show single collection info instead of per-doc collections

---

## Step 10 — Frontend Changes (minimal)

### `client/src/api.js`:
```javascript
export async function uploadDocument(file, docType = 'general') {
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)  // NEW
  // ... rest unchanged
}
```

### `client/src/App.jsx`:
- Add `docType` state (default: 'general')
- Pass `docType` to `uploadDocument()` call
- Pass `docType` + setter to UploadZone

### `client/src/components/UploadZone.jsx`:
- Add doc_type dropdown select:
  - Contract, Medical Report, Book, Resume, General (default)
- Show dropdown above/near the upload zone
- Pass selected value to parent via callback

---

## Step 11 — Migration / Cleanup

1. **Qdrant**: Delete all old per-document collections (`doc_*`)
2. **Supabase**: Add `doc_type` column to `documents` table (default: 'general')
3. **Users**: Must re-upload documents (vectors are incompatible between old/new embedding models)

---

## Implementation Order

1. `requirements.txt` — install new deps
2. `config.py` — add new settings
3. `schemas.py` — add DocType enum + field updates
4. `embeddings.py` — create new file (FastEmbed service)
5. `parser.py` — full rewrite (unstructured + adaptive chunking)
6. `vector_store.py` — full rewrite (single collection, hybrid search)
7. `reranker.py` — create new file (CrossEncoder)
8. `llm.py` — add query transformation + update pipeline
9. `routes.py` — update endpoints for doc_type + user_id passthrough
10. Frontend — add doc_type dropdown
11. Test end-to-end: upload → ask → citations

## Files Changed Summary

| File | Action | Scope |
|------|--------|-------|
| `server/requirements.txt` | MODIFY | ~5 line changes |
| `server/app/core/config.py` | MODIFY | +15 lines |
| `server/app/models/schemas.py` | MODIFY | +12 lines |
| `server/app/services/embeddings.py` | CREATE | ~50 lines |
| `server/app/services/parser.py` | REWRITE | ~250 lines |
| `server/app/services/vector_store.py` | REWRITE | ~250 lines |
| `server/app/services/reranker.py` | CREATE | ~35 lines |
| `server/app/services/llm.py` | MODIFY | ~60 lines changed |
| `server/app/api/routes.py` | MODIFY | ~20 lines changed |
| `client/src/api.js` | MODIFY | ~3 lines |
| `client/src/App.jsx` | MODIFY | ~10 lines |
| `client/src/components/UploadZone.jsx` | MODIFY | ~30 lines |
