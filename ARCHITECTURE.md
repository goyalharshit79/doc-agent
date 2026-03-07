# DocAgent — Complete Architecture & Technical Manual

> **Purpose:** This document is a full reference manual for the DocAgent codebase.
> It covers every flow, every function, every data structure, and every connection
> between components — so you can debug, extend, or rebuild any part of the system
> without needing to reverse-engineer anything.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Stack](#2-technology-stack)
3. [Project Structure](#3-project-structure)
4. [Environment & Configuration](#4-environment--configuration)
5. [Data Model & Storage](#5-data-model--storage)
6. [Flow 1: Authentication](#6-flow-1-authentication)
7. [Flow 2: Document Upload & Processing](#7-flow-2-document-upload--processing)
8. [Flow 3: Asking Questions (RAG Pipeline)](#8-flow-3-asking-questions-rag-pipeline)
9. [Flow 4: Document Library & Deletion](#9-flow-4-document-library--deletion)
10. [Frontend Component Map](#10-frontend-component-map)
11. [Backend Function Reference](#11-backend-function-reference)
12. [Frontend Function Reference](#12-frontend-function-reference)
13. [Error Handling Patterns](#13-error-handling-patterns)
14. [Known Gotchas & Debugging Tips](#14-known-gotchas--debugging-tips)
15. [How to Run Everything](#15-how-to-run-everything)

---

## 1. System Overview

DocAgent is a document intelligence app. Users upload documents (PDF, DOCX, TXT, MD),
which are parsed, chunked, and embedded into a vector database. Users then ask
natural-language questions about a specific document, and the system retrieves relevant
chunks via hybrid search, re-ranks them with a cross-encoder, and generates an answer
with exact citations using Google Gemini.

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite)                       │
│                                                                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ AuthPage │  │ UploadZone│  │ AskPage  │  │  YourDocuments     │  │
│  │          │  │ + FileList│  │ + Preview │  │  (doc library)     │  │
│  └────┬─────┘  └────┬──────┘  └────┬─────┘  └────────┬───────────┘  │
│       │              │              │                  │              │
│       ▼              ▼              ▼                  ▼              │
│  ┌────────────────── api.js ─────────────────────────────────────┐   │
│  │  signup() login() uploadDocument() ask() listDocuments()      │   │
│  │  deleteDocument() computeDocId()                              │   │
│  └───────────────────────────┬───────────────────────────────────┘   │
└──────────────────────────────┼───────────────────────────────────────┘
                               │ HTTP (port 8000)
┌──────────────────────────────┼───────────────────────────────────────┐
│                        BACKEND (FastAPI)                             │
│                               │                                      │
│  ┌────────────────────────────▼──────────────────────────────────┐   │
│  │                      routes.py                                │   │
│  │  POST /upload  GET /documents  DELETE /documents/{id}         │   │
│  │  POST /ask     GET /debug/qdrant                              │   │
│  └──┬──────────────┬──────────────┬──────────────┬───────────────┘   │
│     │              │              │              │                    │
│     ▼              ▼              ▼              ▼                    │
│  ┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │parser  │  │vector    │  │llm       │  │reranker  │              │
│  │.py     │  │_store.py │  │.py       │  │.py       │              │
│  └───┬────┘  └──┬───┬───┘  └────┬─────┘  └────┬─────┘              │
│      │          │   │           │              │                     │
│      │          │   │     ┌─────▼─────┐        │                    │
│      │          │   │     │embeddings │        │                    │
│      │          │   │     │.py        │        │                    │
│      │          │   │     └───────────┘        │                    │
└──────┼──────────┼───┼─────────────────────────┼─────────────────────┘
       │          │   │                          │
       │          │   │                          │
   ┌───▼────┐  ┌──▼───▼──┐  ┌────────────┐  ┌───▼──────────┐
   │unstruc-│  │ Qdrant  │  │ Supabase   │  │cross-encoder │
   │tured   │  │ (vec DB)│  │ (auth+meta)│  │ms-marco      │
   │library │  │ :6333   │  │ (cloud)    │  │MiniLM-L-6    │
   └────────┘  └─────────┘  └────────────┘  └──────────────┘
```

### Data Flow Summary

```
UPLOAD:   File → Parse → Chunk → Embed (dense+sparse) → Store (Qdrant+Supabase)
QUERY:    Question → Rewrite → Hybrid Search → Re-rank → Generate (Gemini) → Citations
DELETE:   Confirm → Remove embeddings (Qdrant) → Remove metadata (Supabase)
RE-UPLOAD: Compute doc_id → Check Supabase → Cache hit? Return instantly : Full pipeline
```

---

## 2. Technology Stack

### Backend
| Component           | Technology                            | Version   |
|---------------------|---------------------------------------|-----------|
| Web framework       | FastAPI                               | 0.111.0   |
| Server              | Uvicorn (ASGI)                        | 0.29.0    |
| Auth & metadata DB  | Supabase (PostgreSQL + GoTrue)        | 2.5.0     |
| Vector database     | Qdrant                                | 1.12.1    |
| Document parsing    | unstructured[pdf,docx]                | latest    |
| Dense embeddings    | BAAI/bge-small-en-v1.5 (via fastembed)| latest    |
| Sparse embeddings   | Qdrant/bm25 (via fastembed)           | latest    |
| Re-ranking          | cross-encoder/ms-marco-MiniLM-L-6-v2  | 3.0.1     |
| LLM (generation)    | Google Gemini 2.5 Flash               | 0.7.2     |
| LLM (query rewrite) | Google Gemini 2.0 Flash Lite          | (same)    |
| Data validation     | Pydantic                              | 2.7.1     |

### Frontend
| Component        | Technology         | Version  |
|------------------|--------------------|----------|
| Framework        | React              | 18.2.0   |
| Build tool       | Vite               | 5.2.0    |
| PDF rendering    | pdfjs-dist         | 4.4.168  |
| DOCX rendering   | mammoth            | 1.8.0    |
| Icons            | lucide-react       | 0.263.1  |
| Fonts            | Cormorant Garamond, IBM Plex Sans/Mono |

### Infrastructure
| Service     | Purpose                                  |
|-------------|------------------------------------------|
| Qdrant      | Vector storage + hybrid search (local)   |
| Supabase    | Auth (JWT), document metadata (Postgres) |
| Google AI   | LLM generation + query rewriting         |

---

## 3. Project Structure

```
app-docagent/
├── server/
│   ├── main.py                          # FastAPI app factory + entry point
│   ├── requirements.txt                 # Python dependencies
│   ├── supabase_schema.sql              # DB schema (reference only)
│   ├── .env                             # Secrets (gitignored)
│   └── app/
│       ├── core/
│       │   ├── config.py                # Settings, env vars, chunk config
│       │   └── auth.py                  # Supabase JWT verification
│       ├── api/
│       │   ├── routes.py                # Main endpoints (upload, ask, docs)
│       │   └── auth_routes.py           # Signup + login endpoints
│       ├── models/
│       │   └── schemas.py               # Pydantic models (request/response)
│       └── services/
│           ├── parser.py                # Document parsing + adaptive chunking
│           ├── embeddings.py            # Dense + sparse embedding generation
│           ├── vector_store.py          # Qdrant + Supabase CRUD
│           ├── llm.py                   # RAG pipeline (Gemini)
│           └── reranker.py              # Cross-encoder re-ranking
│
├── client/
│   ├── index.html                       # HTML shell + Google Fonts
│   ├── package.json                     # Node dependencies
│   ├── vite.config.js                   # Vite config (host, PDF optimize)
│   └── src/
│       ├── main.jsx                     # React entry (StrictMode)
│       ├── App.jsx                      # Root component, state, routing
│       ├── api.js                       # HTTP client for all API calls
│       ├── index.css                    # All styles (~2600 lines)
│       └── components/
│           ├── AuthPage.jsx             # Login / signup form
│           ├── UploadZone.jsx           # Drag-drop file selector
│           ├── FileList.jsx             # Sidebar file list + process button
│           ├── DocumentPreview.jsx      # PDF/DOCX/TXT preview + highlighting
│           ├── AskPage.jsx              # Chat UI + citations + preview
│           └── YourDocuments.jsx        # Document library grid
│
└── .claude/
    └── launch.json                      # Dev server config for preview
```

---

## 4. Environment & Configuration

### Required Environment Variables (server/.env)

```env
GEMINI_API_KEY=your_google_ai_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJ...your_service_role_key
SECRET_KEY=any_random_string_for_fastapi
```

### Optional Environment Variables (with defaults)

```env
CORS_ORIGINS=http://localhost:5173        # Comma-separated allowed origins
QDRANT_HOST=localhost                      # Qdrant server hostname
QDRANT_PORT=6333                           # Qdrant server port
COLLECTION_NAME=documents                  # Qdrant collection name
DENSE_MODEL=BAAI/bge-small-en-v1.5        # 384-dim dense embedding model
SPARSE_MODEL=Qdrant/bm25                  # BM25 sparse embedding model
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RETRIEVAL_TOP_K=15                         # Hybrid search candidate count
RERANK_TOP_K=3                             # Final chunks sent to LLM
LLM_MODEL=gemini-2.5-flash                # Main generation model
QUERY_REWRITE_MODEL=gemini-2.0-flash-lite  # Fast model for query rewriting
```

### Adaptive Chunk Configuration (in config.py)

Each document type has tuned chunk sizes (in words):

| Document Type    | Chunk Size | Overlap | Special Behavior                          |
|------------------|------------|---------|-------------------------------------------|
| `contract`       | 600        | 100     | Numbered clauses promoted to headings     |
| `medical_report` | 500        | 80      | Standard                                  |
| `book`           | 800        | 150     | Larger chunks for narrative flow          |
| `resume`         | 300        | 50      | Sections kept whole if < 1.5× max size   |
| `general`        | 500        | 80      | Default                                   |

---

## 5. Data Model & Storage

### Supabase: `documents` Table

| Column       | Type          | Notes                           |
|--------------|---------------|----------------------------------|
| `doc_id`     | text (PK)     | SHA256(filename:filesize)[:16]   |
| `doc_name`   | text NOT NULL | Original filename                |
| `doc_type`   | text          | contract, resume, general, etc.  |
| `num_chunks` | int NOT NULL  | Number of chunks created         |
| `user_id`    | text          | Supabase auth user UUID          |
| `created_at` | timestamptz   | Auto-set on insert               |

> **Note:** The `supabase_schema.sql` file in the repo is outdated — it doesn't
> include `doc_type` or `user_id`. The actual table was modified to include these
> columns. The code uses upsert, so the schema evolved over time.

### Qdrant: `documents` Collection

**Vector Configuration:**
- **Dense vectors** (named `"dense"`): 384 dimensions, COSINE distance
- **Sparse vectors** (named `"sparse"`): BM25 with IDF modifier

**Payload Indexes:** `user_id`, `doc_id`, `doc_type` (KEYWORD type for fast filtering)

**Point Structure:**
```json
{
  "id": "UUID5(chunk_id)",          // Deterministic UUID from chunk_id
  "vectors": {
    "dense": [0.12, -0.34, ...],    // 384 floats
    "sparse": {
      "indices": [42, 137, 891],    // Token positions
      "values": [1.2, 0.8, 2.1]    // BM25+IDF weights
    }
  },
  "payload": {
    "chunk_id": "abc123_p1_c0",
    "text": "The actual chunk text...",
    "doc_id": "abc123def456gh78",
    "doc_name": "contract.pdf",
    "doc_type": "contract",
    "user_id": "supabase-uuid-...",
    "page_number": 3,
    "heading": "Section 2: Definitions"
  }
}
```

### doc_id Generation

The `doc_id` is deterministic and identical on frontend and backend:

```
doc_id = SHA256("filename.pdf:12345")[:16]
                  ^^^^^^^^     ^^^^^
                  filename     file size in bytes
```

This means:
- Same file → always same `doc_id` (enables cache detection)
- Different content same name → different size → different `doc_id`
- Computed in `server/app/services/parser.py: make_doc_id()`
- Computed in `client/src/api.js: computeDocId()`

### chunk_id Generation

```
chunk_id = "{doc_id}_p{page_number}_c{counter}"
```

Example: `"a1b2c3d4e5f6g7h8_p3_c2"` = doc a1b2..., page 3, chunk index 2

### Qdrant Point ID

```python
point_id = uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id)
```

Deterministic UUID from chunk_id — same chunk always gets same point ID (enables idempotent upserts).

---

## 6. Flow 1: Authentication

```
┌─────────────┐     POST /api/auth/signup      ┌──────────────┐
│  AuthPage   │ ──────────────────────────────► │ auth_routes  │
│  (frontend) │     { email, password }         │  .py         │
│             │                                 │              │
│             │     POST /api/auth/login        │  signup():   │
│             │ ──────────────────────────────► │  → Supabase  │
│             │     { email, password }         │    sign_up() │
│             │                                 │              │
│             │ ◄────────────────────────────── │  login():    │
│             │     { access_token,             │  → Supabase  │
│             │       user_id, email }          │    sign_in() │
└──────┬──────┘                                 └──────────────┘
       │
       │ Stores token in localStorage('docagent_token')
       │
       ▼
  All subsequent API calls include:
  Authorization: Bearer {token}
       │
       ▼
  ┌──────────────────────────────────────────────────────┐
  │  auth.py: get_current_user_id(credentials)           │
  │  → Extracts bearer token                             │
  │  → Calls supabase.auth.get_user(token)               │
  │  → Returns user_id (UUID) or raises 401              │
  └──────────────────────────────────────────────────────┘
```

**Key Points:**
- Auth is fully delegated to Supabase GoTrue
- The backend never stores passwords — Supabase handles hashing
- JWT verification happens on every protected endpoint via FastAPI `Depends()`
- Token expiry is managed by Supabase (default ~1 hour, refresh handled client-side)
- Email confirmation may be enabled in Supabase dashboard (Auth → Settings)

---

## 7. Flow 2: Document Upload & Processing

This is the most complex flow. Here's the complete sequence:

```
USER ACTION: Drag file onto UploadZone (or click browse)
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FRONTEND: App.jsx                                                  │
│                                                                     │
│  handleFilesAdded(newFiles)                                         │
│  ├─ Filter duplicates (by filename)                                │
│  ├─ Create entries: { file, docId: null, status: 'pending' }       │
│  └─ Add to files[] state, set activeIndex                          │
│                                                                     │
│  [User sees file in FileList with "pending" status]                │
│  [User clicks "Process N documents" button]                         │
│                                                                     │
│  handleProcessDocuments()                                           │
│  ├─ Read filesRef.current (avoids StrictMode side-effect bug)      │
│  ├─ Filter entries where status === 'pending'                       │
│  ├─ setIsProcessing(true)                                          │
│  ├─ Mark all pending → 'uploading'                                 │
│  │                                                                  │
│  │  FOR EACH pending file:                                         │
│  │  ├─ POST /api/upload (FormData: file + doc_type)                │
│  │  ├─ On success: status → 'processed', save doc_id               │
│  │  └─ On error: status → 'error', save error message              │
│  │                                                                  │
│  ├─ setIsProcessing(false)                                         │
│  └─ If any succeeded: setActiveDoc(lastDoc), navigate to Ask page  │
└─────────────────────────────────────────────────────────────────────┘
      │
      │ POST /api/upload (multipart: file + doc_type)
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BACKEND: routes.py → upload_document()                             │
│                                                                     │
│  1. VALIDATE                                                        │
│     ├─ Extension check (pdf, docx, txt, md)                        │
│     ├─ DocType enum check (general, contract, medical_report, etc.) │
│     ├─ File size ≤ 50MB                                            │
│     └─ File not empty                                              │
│                                                                     │
│  2. FAST CACHE CHECK (new optimization)                             │
│     ├─ doc_id = make_doc_id(filename, file_size)  ← instant        │
│     ├─ cached = get_doc_meta_by_id(doc_id, user_id)  ← Supabase   │
│     └─ If cached: RETURN immediately with cached metadata           │
│        (skips ALL parsing and embedding — milliseconds)             │
│                                                                     │
│  3. PARSE (if not cached)                                           │
│     └─ parse_document(file_bytes, filename, size, doc_type, user_id)│
│        ├─ _parse_to_elements()  ← unstructured library             │
│        │  └─ Extracts: text, page numbers, categories, headings    │
│        │  └─ Converts to Markdown (tables, lists, headings)        │
│        ├─ _preprocess_contract()  ← only for doc_type="contract"   │
│        │  └─ Promotes numbered clauses to heading boundaries       │
│        ├─ _group_into_sections()                                    │
│        │  └─ Groups content by heading boundaries                  │
│        └─ _chunk_sections()                                         │
│           └─ Splits sections into chunks per doc_type config        │
│           └─ Resume: keeps small sections whole                     │
│           └─ Attaches metadata: chunk_id, doc_id, page, heading    │
│                                                                     │
│  4. EMBED & STORE (if not cached)                                   │
│     └─ process_upload(chunks, doc_id, doc_name, user_id, doc_type) │
│        ├─ doc_vectors_exist(doc_id)  ← Qdrant idempotency check   │
│        ├─ If new: embed_and_store(chunks)                          │
│        │  ├─ EmbeddingService.encode_dual(texts)                   │
│        │  │  ├─ Dense: BAAI/bge-small-en-v1.5 → 384-dim vectors   │
│        │  │  └─ Sparse: Qdrant/bm25 → BM25+IDF sparse vectors     │
│        │  └─ Qdrant upsert (batch, deterministic UUIDs)            │
│        └─ save_doc_meta() → Supabase upsert (always)               │
│                                                                     │
│  5. RESPOND                                                         │
│     └─ { doc_id, doc_name, doc_type, num_chunks, message }         │
└─────────────────────────────────────────────────────────────────────┘
```

### Why Two Dedup Layers?

1. **Supabase check (fast path):** Runs BEFORE parsing. If `doc_id` is already in
   Supabase for this user, the entire parse+embed pipeline is skipped. This is the
   "re-upload optimization" — returns in milliseconds.

2. **Qdrant check (idempotency):** Runs AFTER parsing but BEFORE embedding. If vectors
   already exist for this `doc_id`, embedding is skipped but Supabase metadata is still
   upserted (to update any changed fields). This handles edge cases where Supabase
   metadata was lost but vectors remain.

---

## 8. Flow 3: Asking Questions (RAG Pipeline)

```
USER ACTION: Types question in AskPage, presses Enter
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FRONTEND: AskPage.jsx → handleSend()                              │
│                                                                     │
│  1. Add user message to messages[]                                 │
│  2. Build conversationHistory from last 10 messages                │
│  3. POST /api/ask { question, doc_ids: [activeDoc.doc_id],         │
│                     conversation_history }                          │
│  4. On response: add assistant message with citations              │
│  5. Save to sessionStorage                                         │
└─────────────────────────────────────────────────────────────────────┘
      │
      │ POST /api/ask
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  BACKEND: routes.py → ask_question()                                │
│                                                                     │
│  1. VALIDATE                                                        │
│     ├─ Question not empty                                          │
│     ├─ At least one doc_id                                         │
│     └─ All doc_ids belong to authenticated user (ownership check)  │
│                                                                     │
│  2. RUN RAG PIPELINE (llm.py → run_rag())                          │
│                                                                     │
│     ┌─────────────────────────────────────────────────────────┐     │
│     │  Step A: QUERY TRANSFORMATION                           │     │
│     │  ├─ If no conversation history: use question as-is      │     │
│     │  └─ If history: call Gemini Flash Lite to rewrite       │     │
│     │     └─ Resolves pronouns, creates standalone query       │     │
│     │     └─ Example: "What about section 3?" + history        │     │
│     │        → "What are the termination clauses in section 3?"│     │
│     └─────────────────────────────────────────────────────────┘     │
│                        │                                            │
│                        ▼                                            │
│     ┌─────────────────────────────────────────────────────────┐     │
│     │  Step B: HYBRID RETRIEVAL (top 15)                      │     │
│     │                                                         │     │
│     │  Encode rewritten query:                                │     │
│     │  ├─ Dense: bge-small → 384-dim vector                  │     │
│     │  └─ Sparse: BM25 → sparse vector                       │     │
│     │                                                         │     │
│     │  Qdrant query_points() with:                            │     │
│     │  ├─ Prefetch dense (top 20, COSINE similarity)         │     │
│     │  ├─ Prefetch sparse (top 20, BM25 relevance)           │     │
│     │  ├─ Fusion: Reciprocal Rank Fusion (RRF)               │     │
│     │  ├─ Filter: user_id = X AND doc_id = Y                 │     │
│     │  └─ Return top 15 candidates with payloads              │     │
│     │                                                         │     │
│     │  Single-doc optimization:                               │     │
│     │  ├─ 1 doc_id → MatchValue (exact match, faster)        │     │
│     │  └─ N doc_ids → MatchAny (set match)                   │     │
│     └─────────────────────────────────────────────────────────┘     │
│                        │                                            │
│                        ▼                                            │
│     ┌─────────────────────────────────────────────────────────┐     │
│     │  Step C: CROSS-ENCODER RE-RANKING (top 3)               │     │
│     │                                                         │     │
│     │  Model: cross-encoder/ms-marco-MiniLM-L-6-v2           │     │
│     │                                                         │     │
│     │  For each of 15 candidates:                             │     │
│     │  ├─ Score = CrossEncoder.predict(question, chunk_text)  │     │
│     │  └─ Note: uses ORIGINAL question, not rewritten query   │     │
│     │                                                         │     │
│     │  Sort by score descending, keep top 3                   │     │
│     │  These 3 chunks become the context for generation       │     │
│     └─────────────────────────────────────────────────────────┘     │
│                        │                                            │
│                        ▼                                            │
│     ┌─────────────────────────────────────────────────────────┐     │
│     │  Step D: ANSWER GENERATION (Gemini 2.5 Flash)           │     │
│     │                                                         │     │
│     │  System prompt instructs:                               │     │
│     │  ├─ Output valid JSON only                              │     │
│     │  ├─ Schema: { answer, citations: [{chunk_id, ...}] }   │     │
│     │  └─ Every claim must cite a chunk_id                    │     │
│     │                                                         │     │
│     │  Message to LLM:                                        │     │
│     │  ├─ Retrieved context block (3 re-ranked chunks)        │     │
│     │  ├─ Original question                                   │     │
│     │  └─ Conversation history (for multi-turn)               │     │
│     │                                                         │     │
│     │  Config: response_mime_type = "application/json"        │     │
│     │  (forces JSON output mode in Gemini)                    │     │
│     └─────────────────────────────────────────────────────────┘     │
│                        │                                            │
│                        ▼                                            │
│     ┌─────────────────────────────────────────────────────────┐     │
│     │  Step E: CITATION PARSING                               │     │
│     │                                                         │     │
│     │  _extract_json(response_text)                           │     │
│     │  ├─ Try direct JSON parse                               │     │
│     │  ├─ Try strip markdown fences                           │     │
│     │  ├─ Try regex first JSON object                         │     │
│     │  └─ Try manual brace matching                           │     │
│     │                                                         │     │
│     │  _parse_llm_response(raw, chunk_map)                    │     │
│     │  ├─ Map chunk_ids from LLM → full Citation objects      │     │
│     │  ├─ Include: doc_name, page, heading, quote, score      │     │
│     │  └─ Handle partial matches (substring fallback)         │     │
│     └─────────────────────────────────────────────────────────┘     │
│                                                                     │
│  3. RESPOND                                                         │
│     └─ { answer, citations: [...], search_query }                  │
└─────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  FRONTEND: Citation Display & Highlighting                          │
│                                                                     │
│  Each citation renders as a clickable chip below the answer         │
│  On click:                                                          │
│  ├─ If activeDoc.file exists (session upload):                     │
│  │  ├─ Jump PDF preview to citation's page                         │
│  │  ├─ Highlight citation's quote text in the preview              │
│  │  └─ Uses fuzzy text matching (normalized whitespace + case)     │
│  └─ If no file blob (library document):                            │
│     └─ Show "preview unavailable" notice                           │
└─────────────────────────────────────────────────────────────────────┘
```

### Hybrid Search Explained

DocAgent uses **Reciprocal Rank Fusion (RRF)** to combine two search strategies:

```
Dense Search (semantic):  "What penalties exist for late delivery?"
  → Finds chunks about consequences, damages, breach — even if
    they don't use the exact word "penalties"

Sparse Search (keyword):  "What penalties exist for late delivery?"
  → Finds chunks containing the exact words "penalties", "late",
    "delivery" — good for specific terms and names

RRF Fusion:
  score(chunk) = 1/(k + rank_dense) + 1/(k + rank_sparse)
  → Chunks that rank high in BOTH searches float to the top
  → Chunks that rank high in only ONE search still appear
```

---

## 9. Flow 4: Document Library & Deletion

### Listing Documents

```
USER ACTION: Navigate to Documents page
      │
      ▼
  YourDocuments.jsx: useEffect on mount
      │
      │ GET /api/documents
      ▼
  routes.py → list_documents()
      │
      │ get_user_documents(user_id)
      ▼
  Supabase: SELECT * FROM documents
            WHERE user_id = ? ORDER BY created_at DESC
      │
      ▼
  Frontend renders grid of document cards
  Each card shows: name, type, chunk count, date
```

### Selecting a Document

```
USER ACTION: Click document card in YourDocuments
      │
      ▼
  App.jsx: handleSelectDoc(doc)
  ├─ Check if session file exists with matching doc_id
  │  (if user uploaded it this session, we have the File blob for preview)
  ├─ Set activeDoc = { doc_id, doc_name, doc_type, num_chunks, file? }
  ├─ Clear chat history (sessionStorage)
  └─ Navigate to Ask page
```

### Deleting a Document

```
USER ACTION: Click trash icon on document card
      │
      ▼
  Confirmation dialog appears:
  "This will permanently delete {name} — including all embeddings
   and metadata. This action cannot be undone."
      │
      │ User clicks "Delete"
      ▼
  YourDocuments.jsx: handleDeleteConfirm()
      │
      │ DELETE /api/documents/{doc_id}
      ▼
  routes.py → delete_document()
  ├─ Verify ownership: doc_exists_for_user(doc_id, user_id)
  └─ delete_document_full(doc_id, user_id)
     ├─ delete_document_vectors() → Qdrant: remove all points
     │  (filtered by doc_id + user_id)
     └─ delete_doc_meta() → Supabase: DELETE FROM documents
        WHERE doc_id = ? AND user_id = ?
      │
      ▼
  Frontend: remove card from grid
```

---

## 10. Frontend Component Map

```
App.jsx (root)
│
├─ State: user, activePage, files[], activeDoc, docType, isProcessing
│
├─ IF not authenticated:
│  └─ AuthPage
│     Props: onAuth(userData)
│     State: mode, email, password, loading, error, notice
│     API: signup(), login()
│     Stores: localStorage.docagent_token
│
├─ IF activePage === 'upload':
│  ├─ IF no files:
│  │  └─ UploadZone
│  │     Props: onFilesAdded, docType, onDocTypeChange
│  │     Features: drag-drop, file input, doc type selector
│  │
│  └─ IF files exist:
│     ├─ FileList (sidebar)
│     │  Props: files, activeIndex, onSelect, onRemove, onAddMore,
│     │         onProcess, pendingCount, isProcessing
│     │  Features: file cards, status badges, progress bar, process button
│     │
│     └─ DocumentPreview (main area)
│        Props: file, externalPage?, highlightText?
│        Sub-components: PdfPreview, DocxPreview, TextPreview
│        Features: page navigation, zoom, text layer, citation highlighting
│
├─ IF activePage === 'documents':
│  └─ YourDocuments
│     Props: onSelectDoc, user
│     State: docs[], loading, error, deleteTarget, deleting
│     API: listDocuments(), deleteDocument()
│     Features: doc grid, delete with confirmation, click to query
│
├─ IF activePage === 'ask':
│  └─ AskPage
│     Props: activeDoc, onNavigateToUpload, onNavigateToDocs
│     State: messages[], input, isLoading, previewPage, highlightQuote
│     API: ask()
│     Stores: sessionStorage.docagent_chat_messages
│     Sub-components:
│     ├─ ChatMessage (per message, with citation chips)
│     ├─ TypingIndicator (loading state)
│     └─ DocumentPreview (right panel, with highlighting)
│
└─ IF activePage === 'study' or 'extract':
   └─ PlaceholderPage ("Coming soon")
```

### State Persistence Summary

| Data                | Storage          | Lifetime              |
|---------------------|------------------|-----------------------|
| Auth token          | localStorage     | Until logout          |
| Chat messages       | sessionStorage   | Until tab close       |
| Upload file list    | React state only | Until page reload     |
| Active document     | React state only | Until page reload     |
| Document library    | Supabase (API)   | Permanent (until delete) |

---

## 11. Backend Function Reference

### parser.py

| Function | Signature | Purpose |
|----------|-----------|---------|
| `make_doc_id` | `(filename: str, size: int) → str` | SHA256 hash for dedup |
| `_parse_to_elements` | `(file_bytes, filename) → list[dict]` | Unstructured → Markdown elements |
| `_group_into_sections` | `(parts) → list[dict]` | Group elements by heading boundaries |
| `_preprocess_contract` | `(parts) → list[dict]` | Promote numbered clauses to headings |
| `_chunk_sections` | `(sections, max_words, overlap, ...) → list[dict]` | Split sections into sized chunks |
| `parse_document` | `(file_bytes, filename, size, doc_type, user_id) → (doc_id, chunks)` | Full parse pipeline |

### embeddings.py

| Method | Signature | Purpose |
|--------|-----------|---------|
| `EmbeddingService.get` | `() → EmbeddingService` | Singleton accessor |
| `.encode_dense` | `(texts) → list[list[float]]` | 384-dim vectors |
| `.encode_sparse` | `(texts) → list[SparseEmbedding]` | BM25 sparse vectors |
| `.encode_dual` | `(texts) → (dense, sparse)` | Both at once |
| `.encode_query_dense` | `(query) → list[float]` | Query-optimized dense |
| `.encode_query_sparse` | `(query) → SparseEmbedding` | Query sparse |

### vector_store.py

| Function | Signature | Purpose |
|----------|-----------|---------|
| `get_qdrant_client` | `() → QdrantClient` | Cached client |
| `ensure_collection` | `() → str` | Create collection if missing |
| `doc_vectors_exist` | `(doc_id) → bool` | Qdrant idempotency check |
| `doc_exists_for_user` | `(doc_id, user_id) → bool` | Supabase ownership check |
| `get_doc_meta_by_id` | `(doc_id, user_id) → dict\|None` | Fast cache lookup |
| `get_user_documents` | `(user_id) → list[dict]` | All user's docs |
| `save_doc_meta` | `(doc_id, name, chunks, user_id, type)` | Supabase upsert |
| `embed_and_store` | `(chunks) → int` | Embed + Qdrant upsert |
| `hybrid_search` | `(query, user_id, doc_ids, top_k) → list[ScoredPoint]` | RRF fusion search |
| `keyword_search` | `(query, user_id, doc_ids, top_k) → list[ScoredPoint]` | Pure BM25 search |
| `delete_document_vectors` | `(doc_id, user_id)` | Remove from Qdrant |
| `delete_doc_meta` | `(doc_id, user_id)` | Remove from Supabase |
| `delete_document_full` | `(doc_id, user_id)` | Remove from both |
| `process_upload` | `(chunks, doc_id, name, user_id, type) → dict` | Full upload orchestration |

### llm.py

| Function | Signature | Purpose |
|----------|-----------|---------|
| `transform_query` | `(raw_query, history) → str` | Rewrite with context |
| `_build_context_block` | `(reranked) → str` | Format chunks for LLM |
| `_build_history_for_gemini` | `(history) → list[dict]` | Convert to Gemini format |
| `_extract_json` | `(raw) → dict\|None` | Robust JSON extraction |
| `_parse_llm_response` | `(raw, chunk_map) → (answer, citations)` | Parse LLM output |
| `run_rag` | `(request, user_id) → AskResponse` | Full RAG pipeline |

### reranker.py

| Method | Signature | Purpose |
|--------|-----------|---------|
| `Reranker.get` | `() → Reranker` | Singleton accessor |
| `.rerank` | `(query, results, top_k) → list[tuple]` | Score + sort + filter |

---

## 12. Frontend Function Reference

### api.js

| Function | Signature | Purpose |
|----------|-----------|---------|
| `signup` | `(email, password) → Promise` | Create account |
| `login` | `(email, password) → Promise` | Sign in |
| `computeDocId` | `(file: File) → Promise<string>` | SHA256 hash (Web Crypto) |
| `uploadDocument` | `(file, docType) → Promise` | Upload + process |
| `listDocuments` | `() → Promise<DocMeta[]>` | Get user's docs |
| `deleteDocument` | `(docId) → Promise` | Delete doc |
| `ask` | `(question, docIds, history) → Promise` | RAG query |

### App.jsx Handlers

| Handler | Trigger | Effect |
|---------|---------|--------|
| `handleAuth` | AuthPage success | Sets user state |
| `handleLogout` | Sign out button | Clears all state + storage |
| `handleFilesAdded` | Drop/select files | Adds to files[] as pending |
| `handleProcessDocuments` | Process button | Uploads files, navigates to Ask |
| `handleRemove` | Trash icon on file | Removes from files[] |
| `handleSelectDoc` | Click doc in library | Sets activeDoc, goes to Ask |

### AskPage.jsx Handlers

| Handler | Trigger | Effect |
|---------|---------|--------|
| `handleSend` | Enter key / Send button | Sends question to API |
| `handleClearChat` | Clear button | Resets messages + sessionStorage |
| `handleCitationClick` | Click citation chip | Jumps preview + highlights text |

---

## 13. Error Handling Patterns

### Backend Error Responses

| Status | When | Detail |
|--------|------|--------|
| 400 | Bad extension, bad doc_type, empty file | Descriptive message |
| 401 | Invalid/expired JWT | "Invalid token: ..." |
| 403 | User doesn't own requested doc_ids | "Access denied to one or more documents" |
| 404 | Delete non-existent doc | "Document not found" |
| 413 | File > 50MB | "File too large (max 50MB)" |
| 422 | No text extracted from file | "No text could be extracted" |
| 500 | Any unhandled exception | "Processing failed: {error}" |

### Backend Graceful Degradation

| Service | On Failure | Fallback |
|---------|-----------|----------|
| Supabase metadata query | Log warning | Return `False`/`None`/`[]` |
| Query rewriting (Gemini Lite) | Log warning | Use original query as-is |
| Re-ranker (CrossEncoder) | Log warning | Use raw search results[:3] |
| JSON extraction from LLM | Log warning | Return (raw_text, []) |
| Partial chunk_id match | Log info | Try substring match |

### Frontend Error Handling

| Scenario | Behavior |
|----------|----------|
| Upload fails | File shows red "Failed" status with error code |
| Ask fails | Error message in chat bubble |
| Document list fails | Error banner with dismiss button |
| Delete fails | Error banner with dismiss button |
| No activeDoc on Ask page | Guard state with navigation buttons |
| sessionStorage quota | Clears storage, continues |

---

## 14. Known Gotchas & Debugging Tips

### React StrictMode Double-Invoke Bug

**Problem:** `React.StrictMode` (in `main.jsx`) double-invokes state updater functions
in development. If you use side effects inside `setFiles(prev => { ... side effect ... })`,
the side effect runs twice and can break logic.

**Solution:** The codebase uses `filesRef = useRef(files)` to snapshot state outside
the updater. Always read from refs in async handlers, never use side effects in updaters.

### First Run is Slow

On first startup, the backend downloads three ML models (~500MB total):
- BAAI/bge-small-en-v1.5 (~130MB)
- Qdrant/bm25 (~50MB)
- cross-encoder/ms-marco-MiniLM-L-6-v2 (~80MB)

These are cached in `~/.cache/huggingface/` and load instantly on subsequent runs.

### Qdrant Must Be Running

Start Qdrant before the backend. Default: Docker on port 6333.
```bash
docker run -p 6333:6333 qdrant/qdrant
```

### CORS Origins

If you change the frontend port, update `CORS_ORIGINS` in `.env`:
```env
CORS_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:5175
```

### The .env File Doesn't Copy to Git Worktrees

Git worktrees share the `.git` directory but not untracked/gitignored files.
You must manually copy `.env` to any worktree's `server/` directory.

### unstructured Library on Windows

The parser uses `strategy="fast"` (no OCR, no layout models). This is intentional —
the default "auto" strategy requires `tesseract`, `poppler`, and other system deps
that are painful on Windows. If you need OCR support, install those deps and change
the strategy in `parser.py`.

### Supabase Schema vs Code

The `supabase_schema.sql` file is outdated. The actual `documents` table has evolved
to include `doc_type` and `user_id` columns that aren't in the SQL file. The code
uses `upsert`, so as long as the columns exist in Supabase, everything works.

### How to Check What's in Qdrant

Visit `http://localhost:8000/api/debug/qdrant` (no auth required) to see:
- Collection exists / doesn't exist
- Total vector count
- Sample points with metadata

### PDF.js Worker

The PDF preview lazy-loads the PDF.js worker from CDN. If you're offline or behind
a firewall, the preview won't work. To fix, bundle the worker locally.

### Chat Persistence is Per-Tab

Chat messages are stored in `sessionStorage`, which is per-tab. Opening a new tab
starts a fresh chat. Closing the tab loses the chat. This is intentional — it
prevents stale conversations from leaking between documents.

---

## 15. How to Run Everything

### Prerequisites

1. **Python 3.11+** (3.14 may have wheel issues with pydantic-core)
2. **Node.js 18+**
3. **Docker** (for Qdrant)
4. **Supabase account** with a project
5. **Google AI API key** (for Gemini)

### Step 1: Start Qdrant

```bash
docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant
```

### Step 2: Configure Environment

```bash
cd server
cp .env.example .env  # or create .env manually
# Fill in: GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY, SECRET_KEY
```

### Step 3: Start Backend

```bash
cd server
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend runs on `http://localhost:8000`

### Step 4: Start Frontend

```bash
cd client
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`

### Step 5: Verify

1. Open `http://localhost:5173` → should see login page
2. Create account → should redirect to upload page
3. Upload a PDF → should process and navigate to Ask page
4. Ask a question → should get answer with citations
5. Check `http://localhost:8000/api/debug/qdrant` → should show vectors
6. Navigate to Documents → should show uploaded doc in library

---

*Last updated: March 2026*
*This document was generated from a complete codebase analysis.*
