# DocAgent

> Document intelligence app — upload documents, ask questions, get cited answers.

Users upload PDFs, DOCX, TXT, or MD files. Documents are parsed, chunked adaptively by type, and embedded into Vertex AI Vector Search. Questions go through a full RAG pipeline: query rewrite, hybrid retrieval, cross-encoder reranking, and answer generation with exact citations via Google Gemini.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite)                       │
│                                                                      │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ AuthPage │  │ UploadZone│  │ AskPage  │  │  YourDocuments     │  │
│  │          │  │ + FileList│  │ + Preview │  │  (doc library)     │  │
│  └────┬─────┘  └────┬──────┘  └────┬─────┘  └────────┬───────────┘  │
│       └──────────────┴──────────────┴────────────────┘              │
│                          api.js                                      │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ HTTP
┌──────────────────────────┼───────────────────────────────────────────┐
│                    BACKEND (FastAPI)                                  │
│                           │                                          │
│  ┌────────────────────────▼──────────────────────────────────────┐   │
│  │  routes.py / auth_routes.py                                   │   │
│  └──┬──────────────┬──────────────┬──────────────┬───────────────┘   │
│     ▼              ▼              ▼              ▼                   │
│  parser.py    vector_store.py   llm.py      reranker.py             │
│                    │               │                                 │
│                    │         embeddings.py                           │
└────────────────────┼───────────────┼─────────────────────────────────┘
                     │               │
              ┌──────▼──────┐  ┌─────▼────────┐  ┌──────────────┐
              │ Vertex AI   │  │ Supabase     │  │ Google       │
              │ Vector      │  │ (auth + meta)│  │ Gemini       │
              │ Search      │  │              │  │              │
              └─────────────┘  └──────────────┘  └──────────────┘
```

### Data Flows

```
UPLOAD:  File → Parse (unstructured) → Adaptive Chunk → Embed (dense+sparse) → Store (Vertex AI + Supabase)
QUERY:   Question → Rewrite (Gemini Flash) → Hybrid Search → Rerank (CrossEncoder) → Generate (Gemini Pro) → Citations
DELETE:  Confirm → Remove vectors (Vertex AI) → Remove metadata (Supabase)
RE-UPLOAD: doc_id match in Supabase → return cached metadata instantly (skip entire pipeline)
```

---

## Tech Stack

### Backend
| Component        | Technology                                |
|------------------|-------------------------------------------|
| Web framework    | FastAPI + Uvicorn                         |
| Vector search    | Google Vertex AI Vector Search            |
| Auth & metadata  | Supabase (PostgreSQL + GoTrue)            |
| Document parsing | unstructured[pdf,docx]                    |
| Dense embeddings | BAAI/bge-small-en-v1.5 (fastembed)        |
| Sparse embeddings| Qdrant/bm25 (fastembed)                   |
| Reranking        | cross-encoder/ms-marco-MiniLM-L-6-v2     |
| LLM (answers)    | Google Gemini 2.5 Pro                     |
| LLM (rewrite)    | Google Gemini 2.5 Flash                   |
| Retry/backoff    | tenacity (exponential backoff on GCP)     |

### Frontend
| Component      | Technology                               |
|----------------|------------------------------------------|
| Framework      | React 18 + Vite                          |
| Markdown       | react-markdown + remark-gfm             |
| PDF preview    | pdfjs-dist                               |
| DOCX preview   | mammoth                                  |
| Icons          | lucide-react                             |

---

## Project Structure

```
app-docagent/
├── server/
│   ├── main.py                    # FastAPI app factory + entry point
│   ├── Dockerfile                 # Cloud Run deployment
│   ├── .dockerignore
│   ├── .env.example               # Required env vars template
│   ├── requirements.txt
│   └── app/
│       ├── core/
│       │   ├── config.py          # Settings (pydantic-settings)
│       │   ├── auth.py            # Supabase JWT verification
│       │   └── retry.py          # Exponential backoff for GCP calls
│       ├── api/
│       │   ├── routes.py          # /upload, /ask, /documents
│       │   └── auth_routes.py     # /auth/signup, /auth/login
│       ├── models/
│       │   └── schemas.py         # Pydantic request/response models
│       └── services/
│           ├── parser.py          # Document parsing + adaptive chunking
│           ├── embeddings.py      # Dense + sparse embeddings (batched)
│           ├── vector_store.py    # Vertex AI + Supabase CRUD
│           ├── llm.py             # RAG pipeline (Gemini)
│           └── reranker.py        # Cross-encoder reranking
│
└── client/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx                # Root component, routing, state
        ├── api.js                 # HTTP client + auth + timeout
        ├── index.css              # All styles
        └── components/
            ├── AuthPage.jsx       # Login / signup
            ├── UploadZone.jsx     # Drag-drop file selector
            ├── FileList.jsx       # Sidebar file list
            ├── DocumentPreview.jsx # PDF/DOCX/TXT preview + citation highlighting
            ├── AskPage.jsx        # Chat UI + citations + side preview
            └── YourDocuments.jsx  # Document library grid
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- GCP project with Vertex AI Vector Search index deployed
- Supabase project
- Google Cloud credentials configured (`gcloud auth application-default login`)

### Backend

```bash
cd server
cp .env.example .env         # fill in your values
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
uvicorn main:app --reload
```

Runs on `http://localhost:8000`. First startup downloads ~500MB of ML models (cached in `~/.cache/`).

### Frontend

```bash
cd client
npm install
npm run dev
```

Runs on `http://localhost:5173`.

---

## Environment Variables

### Required (server/.env)

```env
GCP_PROJECT=your-gcp-project-id
GCP_LOCATION=us-central1
VERTEX_INDEX_ENDPOINT_ID=your-index-endpoint-id
VERTEX_INDEX_ID=your-index-id
VERTEX_DEPLOYED_INDEX_ID=your-deployed-index-id
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
SECRET_KEY=random-string-for-jwt
CORS_ORIGINS=http://localhost:5173
```

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `THREAD_POOL_SIZE` | 16 | Concurrent GCP call workers |
| `PORT` | 8000 | Server port (Cloud Run sets this) |
| `DENSE_MODEL` | BAAI/bge-small-en-v1.5 | 384-dim dense embedding model |
| `SPARSE_MODEL` | Qdrant/bm25 | BM25 sparse embedding model |
| `RERANKER_MODEL` | cross-encoder/ms-marco-MiniLM-L-6-v2 | Cross-encoder model |
| `LLM_MODEL` | gemini-2.5-pro | Answer generation model |
| `QUERY_REWRITE_MODEL` | gemini-2.5-flash | Query rewrite model |
| `RETRIEVAL_TOP_K` | 15 | Hybrid search candidates |
| `RERANK_TOP_K` | 5 | Final chunks sent to LLM |

### Client Build

Set `VITE_API_URL` at build time to point to the deployed backend:

```bash
VITE_API_URL=https://your-backend.run.app/api npm run build
```

Falls back to `http://localhost:8000/api` in development.

---

## Data Model

### Supabase: `documents` Table

| Column       | Type        | Notes                          |
|--------------|-------------|--------------------------------|
| `doc_id`     | text (PK)   | SHA256(filename:filesize)[:16] |
| `doc_name`   | text        | Original filename              |
| `doc_type`   | text        | contract, resume, general, etc |
| `num_chunks` | int         | Number of chunks               |
| `user_id`    | text        | Supabase auth UUID             |
| `created_at` | timestamptz | Auto-set                       |

### Vertex AI Vector Search

Each chunk is stored as a datapoint with:
- **Dense vector**: 384 dimensions (BAAI/bge-small-en-v1.5)
- **Sparse vector**: BM25+IDF token weights
- **Restricts/metadata**: `user_id`, `doc_id`, `doc_type`, `chunk_id`, `text`, `page_number`, `heading`

### ID Generation

```
doc_id   = SHA256("filename.pdf:12345")[:16]    # deterministic, computed on both client and server
chunk_id = "{doc_id}_p{page}_c{counter}"        # e.g. "a1b2c3d4e5f6g7h8_p3_c2"
```

Same file always produces the same `doc_id`, enabling instant cache hits on re-upload.

---

## RAG Pipeline

```
Question
    │
    ▼
Query Rewrite (Gemini Flash)
    │  Fix spelling, grammar, resolve pronouns from chat history
    │  Always runs — even without history (catches typos)
    ▼
Hybrid Retrieval (top 15)
    │  Dense: semantic similarity (bge-small)
    │  Sparse: keyword matching (BM25)
    │  Fusion: Reciprocal Rank Fusion
    │  Filter: user_id + doc_id
    ▼
Cross-Encoder Reranking (top 5)
    │  ms-marco-MiniLM-L-6-v2
    │  Scores each (question, chunk) pair
    ▼
Answer Generation (Gemini Pro)
    │  JSON mode: { answer, citations[] }
    │  Each citation: chunk_id, quote, page, heading
    ▼
Citation Parsing
    │  Robust JSON extraction (4 fallback strategies)
    │  Chunk ID regex safety net
    ▼
Response → Frontend renders answer with clickable citation chips
```

### Adaptive Chunking

Documents are chunked differently based on type:

| Type            | Chunk Size (words) | Overlap | Notes                            |
|-----------------|-------------------|---------|----------------------------------|
| `contract`      | 600               | 100     | Numbered clauses → heading breaks |
| `medical_report`| 500               | 80      | Standard                         |
| `book`          | 800               | 150     | Larger for narrative flow        |
| `resume`        | 200               | 30      | Small sections kept whole        |
| `general`       | 500               | 80      | Default                          |

---

## Deployment (GCP Cloud Run)

The backend includes a production-ready Dockerfile.

```bash
cd server

# Build and deploy
gcloud run deploy docagent-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GCP_PROJECT=...,GCP_LOCATION=us-central1,VERTEX_INDEX_ENDPOINT_ID=...,VERTEX_INDEX_ID=...,VERTEX_DEPLOYED_INDEX_ID=...,SUPABASE_URL=...,SUPABASE_SERVICE_KEY=...,SECRET_KEY=...,CORS_ORIGINS=https://your-frontend.com"
```

Then build the client with the Cloud Run URL:

```bash
cd client
VITE_API_URL=https://docagent-api-xxx-uc.a.run.app/api npm run build
# Deploy dist/ to any static host (Vercel, Netlify, GCS bucket, etc.)
```

---

## Error Handling

### Backend

- All GCP calls (Vertex AI, Gemini) use **exponential backoff** via tenacity (3 retries, 2-30s wait)
- Graceful degradation: query rewrite failure → use original query; reranker failure → use raw results
- Input validation: file type, size (50MB max), doc ownership checks

### Frontend

- **Configurable fetch timeouts**: 5min (upload), 3min (ask), 2min (default) via AbortController
- **Token auto-refresh**: 401 → refresh token → retry original request once
- **User-friendly errors**: `friendlyError()` maps HTTP codes and network errors to readable messages
- **Chat persistence**: sessionStorage (per-tab, survives page nav within tab)

---

## Citation Highlighting

When a citation chip is clicked in the chat:
1. Preview jumps to the citation's page
2. Citation quote text is matched against the preview using:
   - **Markdown stripping** — removes formatting added by the parser
   - **Character-level normalization** — whitespace/case-insensitive matching with original index mapping
   - **Progressive fallback** — tries full quote first, then progressively shorter prefixes (down to 30 chars)

---

## Notes

- **First run is slow** — downloads ~500MB of ML models (bge-small, BM25, cross-encoder). Cached after first download.
- **CORS** — update `CORS_ORIGINS` in `.env` when changing frontend URL/port (comma-separated).
- **Embeddings are batched** (64 texts/batch) to prevent OOM on large documents.
- **Chunk IDs are stripped** from LLM answers via regex safety net, in case the model leaks them.
- **PDF.js worker** loads from CDN — preview requires internet on first load.
