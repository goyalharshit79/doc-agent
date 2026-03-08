# DocAgent

> Document intelligence platform — upload documents, ask questions, get cited answers. Monetized with Razorpay subscriptions, managed via an admin console.

Users upload PDFs, DOCX, TXT, or MD files. Documents are parsed, chunked adaptively by type, and embedded into Vertex AI Vector Search. Questions go through a full RAG pipeline: query rewrite, hybrid retrieval, cross-encoder reranking, and answer generation with exact citations via Google Gemini.

Free tier users get 1 document and 10 queries/day. Pro subscribers get 20 documents and unlimited queries.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React + Vite)                          │
│                                                                         │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌────────────────────────┐  │
│  │ AuthPage │  │ UploadZone│  │ AskPage  │  │  YourDocuments         │  │
│  │ (login,  │  │ + FileList│  │ + Preview │  │  (doc library)         │  │
│  │  signup, │  │           │  │ + Chat    │  │                        │  │
│  │  reset)  │  │           │  │           │  │                        │  │
│  └────┬─────┘  └────┬──────┘  └────┬─────┘  └────────┬───────────────┘  │
│       │              │              │                  │                 │
│  ┌────▼──────────────▼──────────────▼──────────────────▼───────────────┐ │
│  │  UsageBadge · UpgradeModal · AdminConsole                          │ │
│  └────────────────────────────┬───────────────────────────────────────┘ │
│                               │  api.js                                 │
└───────────────────────────────┼─────────────────────────────────────────┘
                                │ HTTP
┌───────────────────────────────┼─────────────────────────────────────────┐
│                         BACKEND (FastAPI)                                │
│                                │                                        │
│  ┌─────────────────────────────▼──────────────────────────────────────┐  │
│  │  routes.py · auth_routes.py · billing_routes.py · admin_routes.py │  │
│  └──┬──────────┬──────────┬──────────┬──────────┬────────────────────┘  │
│     ▼          ▼          ▼          ▼          ▼                       │
│  parser.py  vector_store  llm.py  reranker   billing.py                │
│               .py           │      .py         │                       │
│                │       embeddings.py         guards.py                  │
└────────────────┼─────────────┼───────────┬─────────────────────────────┘
                 │             │           │
          ┌──────▼──────┐ ┌───▼────────┐ ┌▼─────────────┐ ┌────────────┐
          │ Vertex AI   │ │ Google     │ │ Supabase     │ │ Razorpay   │
          │ Vector      │ │ Gemini     │ │ (auth + meta │ │ (payments) │
          │ Search      │ │            │ │  + profiles) │ │            │
          └─────────────┘ └────────────┘ └──────────────┘ └────────────┘
```

### Data Flows

```
UPLOAD:  File → Parse (unstructured) → Adaptive Chunk → Embed (dense+sparse) → Store (Vertex AI + Supabase)
         ↳ Guard: check_upload_limit (plan-based document cap)

QUERY:   Question → Rewrite (Gemini Flash) → Hybrid Search → Rerank (CrossEncoder) → Generate (Gemini Pro) → Citations
         ↳ Guard: check_query_limit (daily query cap for free tier)

DELETE:  Confirm → Remove vectors (Vertex AI) → Remove metadata (Supabase) → Refresh usage

RE-UPLOAD: doc_id match in Supabase → return cached metadata instantly (skip entire pipeline)

SUBSCRIBE: Upgrade click → Razorpay checkout → Webhook → plan=pro, is_unlimited=true

CANCEL:  Razorpay webhook (cancelled/expired) → plan=free, is_unlimited=false
```

---

## Tech Stack

### Backend

| Component         | Technology                             |
| ----------------- | -------------------------------------- |
| Web framework     | FastAPI + Uvicorn                      |
| Vector search     | Google Vertex AI Vector Search         |
| Auth & metadata   | Supabase (PostgreSQL + GoTrue)         |
| Document parsing  | unstructured[pdf,docx]                 |
| Dense embeddings  | BAAI/bge-small-en-v1.5 (fastembed)     |
| Sparse embeddings | Qdrant/bm25 (fastembed)                |
| Reranking         | cross-encoder/ms-marco-MiniLM-L-6-v2   |
| LLM (answers)     | Google Gemini 2.5 Pro                  |
| LLM (rewrite)     | Google Gemini 2.5 Flash                |
| Retry/backoff     | tenacity (exponential backoff on GCP)  |
| Payments          | Razorpay Subscriptions API             |

### Frontend

| Component    | Technology                  |
| ------------ | --------------------------- |
| Framework    | React 18 + Vite             |
| Markdown     | react-markdown + remark-gfm |
| PDF preview  | pdfjs-dist                  |
| DOCX preview | mammoth                     |
| Icons        | lucide-react                |
| Local storage| idb-keyval (IndexedDB)      |

---

## Project Structure

```
app-docagent/
├── server/
│   ├── main.py                    # FastAPI app + router registration
│   ├── Dockerfile                 # Cloud Run deployment
│   ├── .env.example               # Required env vars template
│   ├── requirements.txt
│   └── app/
│       ├── core/
│       │   ├── config.py          # Settings (pydantic-settings, plan limits, Razorpay config)
│       │   ├── auth.py            # Supabase JWT verification
│       │   ├── guards.py          # Plan-limit enforcement (upload + query guards)
│       │   └── retry.py           # Exponential backoff for GCP calls
│       ├── api/
│       │   ├── routes.py          # /upload, /ask, /documents, /delete, /usage
│       │   ├── auth_routes.py     # /auth/signup, /login, /refresh, /forgot-password, /reset-password
│       │   ├── billing_routes.py  # /billing/subscribe, /billing/webhook/razorpay
│       │   └── admin_routes.py    # /admin/users (list, update plan, delete)
│       ├── models/
│       │   └── schemas.py         # Pydantic request/response models
│       └── services/
│           ├── parser.py          # Document parsing + adaptive chunking
│           ├── embeddings.py      # Dense + sparse embeddings (batched)
│           ├── vector_store.py    # Vertex AI + Supabase CRUD
│           ├── llm.py             # RAG pipeline (Gemini)
│           ├── reranker.py        # Cross-encoder reranking
│           └── billing.py         # User profiles, plan limits, Razorpay API + webhook handler
│
└── client/
    ├── index.html                 # Entry HTML + Razorpay checkout script
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx                # Root component, routing, auth, billing state
        ├── api.js                 # HTTP client + structured error handling + auth
        ├── index.css              # All styles
        └── components/
            ├── AuthPage.jsx       # Login / signup / forgot password / reset password
            ├── UploadZone.jsx     # Drag-drop file selector
            ├── FileList.jsx       # Sidebar file list
            ├── DocumentPreview.jsx# PDF/DOCX/TXT preview + citation highlighting
            ├── AskPage.jsx        # Chat UI + citations + side preview
            ├── YourDocuments.jsx  # Document library grid
            ├── UsageBadge.jsx     # Plan badge + usage counters in header
            ├── UpgradeModal.jsx   # Razorpay checkout flow
            └── AdminConsole.jsx   # Admin user management table
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- GCP project with Vertex AI Vector Search index deployed
- Supabase project (with `documents` and `user_profiles` tables)
- Razorpay account (for payments)
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
# Google Cloud / Vertex AI
GCP_PROJECT=your-gcp-project-id
GCP_LOCATION=us-central1
VERTEX_INDEX_ENDPOINT_ID=your-index-endpoint-id
VERTEX_INDEX_ID=your-index-id
VERTEX_DEPLOYED_INDEX_ID=your-deployed-index-id

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key

# App
SECRET_KEY=random-string-for-jwt
CORS_ORIGINS=http://localhost:5173

# Razorpay
RAZORPAY_KEY_ID=rzp_live_xxxx
RAZORPAY_KEY_SECRET=your-razorpay-key-secret
RAZORPAY_PLAN_ID=plan_xxxx
RAZORPAY_WEBHOOK_SECRET=your-razorpay-webhook-secret

# Admin
ADMIN_EMAIL=your-admin-email@example.com
```

### Optional

| Variable                   | Default                               | Purpose                           |
| -------------------------- | ------------------------------------- | --------------------------------- |
| `THREAD_POOL_SIZE`         | 16                                    | Concurrent GCP call workers       |
| `PORT`                     | 8000                                  | Server port (Cloud Run sets this) |
| `FREE_MAX_DOCUMENTS`       | 1                                     | Max docs for free tier            |
| `FREE_MAX_QUERIES_PER_DAY` | 10                                    | Max daily queries for free tier   |
| `PRO_MAX_DOCUMENTS`        | 20                                    | Max docs for pro tier             |
| `DENSE_MODEL`              | BAAI/bge-small-en-v1.5                | 384-dim dense embedding model     |
| `SPARSE_MODEL`             | Qdrant/bm25                           | BM25 sparse embedding model       |
| `RERANKER_MODEL`           | cross-encoder/ms-marco-MiniLM-L-6-v2  | Cross-encoder model               |
| `LLM_MODEL`                | gemini-2.5-pro                        | Answer generation model           |
| `QUERY_REWRITE_MODEL`      | gemini-2.5-flash                      | Query rewrite model               |
| `RETRIEVAL_TOP_K`          | 15                                    | Hybrid search candidates          |
| `RERANK_TOP_K`             | 5                                     | Final chunks sent to LLM          |

### Client Build

Set `VITE_API_URL` at build time to point to the deployed backend:

```bash
VITE_API_URL=https://your-backend.run.app/api npm run build
```

Falls back to `http://localhost:8000/api` in development.

---

## Data Model

### Supabase Tables

#### `documents`

| Column       | Type        | Notes                          |
| ------------ | ----------- | ------------------------------ |
| `doc_id`     | text (PK)   | SHA256(filename:filesize)[:16] |
| `doc_name`   | text        | Original filename              |
| `doc_type`   | text        | contract, resume, general, etc |
| `num_chunks` | int         | Number of chunks               |
| `user_id`    | text        | Supabase auth UUID             |
| `created_at` | timestamptz | Auto-set                       |

#### `user_profiles`

| Column                     | Type        | Notes                                  |
| -------------------------- | ----------- | -------------------------------------- |
| `user_id`                  | uuid (PK)   | References auth.users                  |
| `plan`                     | text        | `free` or `pro`                        |
| `is_unlimited`             | boolean     | Bypasses all limits (auto-set by plan) |
| `queries_today`            | int         | Daily query counter                    |
| `query_date`               | date        | Resets counter on new day              |
| `razorpay_customer_id`     | text        | Razorpay customer ID                   |
| `razorpay_subscription_id` | text        | Active subscription ID                 |
| `subscription_status`      | text        | active, cancelled, halted, etc         |
| `created_at`               | timestamptz | Auto-set                               |

A database trigger auto-creates a `user_profiles` row when a new user signs up.

#### `razorpay_events`

| Column       | Type        | Notes                           |
| ------------ | ----------- | ------------------------------- |
| `id`         | serial (PK) | Auto-increment                  |
| `event_type` | text        | e.g. subscription.activated     |
| `payload`    | jsonb       | Full webhook payload            |
| `created_at` | timestamptz | Auto-set                        |

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

| Type             | Chunk Size (words) | Overlap | Notes                             |
| ---------------- | ------------------ | ------- | --------------------------------- |
| `contract`       | 600                | 100     | Numbered clauses = heading breaks |
| `medical_report` | 500                | 80      | Standard                          |
| `book`           | 800                | 150     | Larger for narrative flow         |
| `resume`         | 200                | 30      | Small sections kept whole         |
| `general`        | 500                | 80      | Default                           |

---

## Monetization

### Plan Tiers

| Feature            | Free          | Pro (paid)          |
| ------------------ | ------------- | ------------------- |
| Documents          | 1             | 20                  |
| Queries per day    | 10            | Unlimited           |
| `is_unlimited`     | false         | true (auto-set)     |

### Subscription Flow

1. User hits a limit (upload or query) → **UpgradeModal** opens
2. Frontend calls `POST /billing/subscribe` → creates Razorpay customer + subscription
3. Razorpay Checkout.js popup opens → user completes payment
4. Razorpay sends `subscription.activated` webhook → backend sets `plan=pro`, `is_unlimited=true`
5. On cancellation/expiry → backend reverts to `plan=free`, `is_unlimited=false`

### Admin Console

Accessible only to the configured `ADMIN_EMAIL`. Provides:

- View all users with plan, unlimited status, document count, subscription status
- Toggle user plan (free/pro) — automatically sets `is_unlimited` to match
- Toggle unlimited flag independently
- Delete users (cascading: vectors, documents, profile, auth)

### Razorpay Webhook Setup

1. In Razorpay Dashboard (Live Mode) → Settings → Webhooks → Add New Webhook
2. URL: `https://your-cloud-run-url/api/billing/webhook/razorpay`
3. Set a secret (save it as `RAZORPAY_WEBHOOK_SECRET` in your env)
4. Subscribe to: `subscription.activated`, `.charged`, `.cancelled`, `.completed`, `.expired`, `.halted`, `.pending`

---

## Authentication

### Flows

| Flow             | Endpoint                    | Notes                                       |
| ---------------- | --------------------------- | ------------------------------------------- |
| Sign up          | `POST /auth/signup`         | Creates Supabase user, returns JWT          |
| Sign in          | `POST /auth/login`          | Validates credentials, returns JWT          |
| Token refresh    | `POST /auth/refresh`        | Exchanges refresh token for new access token|
| Forgot password  | `POST /auth/forgot-password`| Sends Supabase reset email                  |
| Reset password   | `POST /auth/reset-password` | Accepts `token_hash` (modern) or `access_token` (legacy) |

### Password Reset Flow

1. User clicks "Forgot password?" on login screen
2. Enters email → backend calls `sb.auth.reset_password_email()`
3. User clicks reset link in email → redirected to frontend with `?token_hash=xxx&type=recovery`
4. Frontend detects token in URL, shows "Set new password" form (with confirm password)
5. User enters new password (twice) → sent to backend with the token hash
6. Backend calls `sb.auth.verify_otp()` to validate, then `admin.update_user_by_id()` to set new password

Both signup and reset password forms require password confirmation (retype to match).

---

## Deployment

### Backend (GCP Cloud Run)

```bash
cd server

gcloud run deploy docagent-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GCP_PROJECT=...,GCP_LOCATION=us-central1,VERTEX_INDEX_ENDPOINT_ID=...,VERTEX_INDEX_ID=...,VERTEX_DEPLOYED_INDEX_ID=...,SUPABASE_URL=...,SUPABASE_SERVICE_KEY=...,SECRET_KEY=...,CORS_ORIGINS=https://your-frontend.com,RAZORPAY_KEY_ID=...,RAZORPAY_KEY_SECRET=...,RAZORPAY_PLAN_ID=...,RAZORPAY_WEBHOOK_SECRET=...,ADMIN_EMAIL=..."
```

### Frontend (Vercel / any static host)

```bash
cd client
VITE_API_URL=https://docagent-api-xxx-uc.a.run.app/api npm run build
# Deploy dist/ to Vercel, Netlify, GCS bucket, etc.
```

### Supabase Configuration

1. **URL Configuration**: Set Site URL to your production frontend URL
2. **Redirect URLs**: Add your frontend URL to the allowlist
3. **Email Templates**: Ensure Reset Password template uses `{{ .ConfirmationURL }}` or token hash format

---

## Error Handling

### Backend

- All GCP calls (Vertex AI, Gemini) use **exponential backoff** via tenacity (3 retries, 2-30s wait)
- Graceful degradation: query rewrite failure → use original query; reranker failure → use raw results
- Input validation: file type, size (50MB max), doc ownership checks
- **Structured guard errors**: `DOCUMENT_LIMIT` (403) and `QUERY_LIMIT` (429) return `{code, message, current, limit, plan}`

### Frontend

- **Configurable fetch timeouts**: 5min (upload), 3min (ask), 2min (default) via AbortController
- **Token auto-refresh**: 401 → refresh token → retry original request once
- **Structured error parsing**: `handleResponse()` extracts guard error codes and attaches them to Error objects
- **Limit handling**: `DOCUMENT_LIMIT` → opens upgrade modal; `QUERY_LIMIT` → shows limit message + upgrade prompt
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

## API Reference

### Core Endpoints

| Method | Path                        | Auth     | Description                                  |
| ------ | --------------------------- | -------- | -------------------------------------------- |
| POST   | `/api/upload`               | Required | Upload + process document (guard: upload limit) |
| POST   | `/api/ask`                  | Required | Ask a question (guard: query limit)          |
| GET    | `/api/documents`            | Required | List user's documents                        |
| DELETE | `/api/documents/{doc_id}`   | Required | Delete document + vectors                    |
| GET    | `/api/usage`                | Required | Get current plan, limits, usage              |

### Auth Endpoints

| Method | Path                        | Auth     | Description                    |
| ------ | --------------------------- | -------- | ------------------------------ |
| POST   | `/api/auth/signup`          | None     | Create account                 |
| POST   | `/api/auth/login`           | None     | Sign in                        |
| POST   | `/api/auth/refresh`         | None     | Refresh access token           |
| POST   | `/api/auth/forgot-password` | None     | Send password reset email      |
| POST   | `/api/auth/reset-password`  | None     | Reset password with token      |

### Billing Endpoints

| Method | Path                              | Auth     | Description                    |
| ------ | --------------------------------- | -------- | ------------------------------ |
| POST   | `/api/billing/subscribe`          | Required | Create Razorpay subscription   |
| POST   | `/api/billing/webhook/razorpay`   | HMAC     | Handle Razorpay webhook events |

### Admin Endpoints

| Method | Path                        | Auth      | Description                    |
| ------ | --------------------------- | --------- | ------------------------------ |
| GET    | `/api/admin/users`          | Admin     | List all users + profiles      |
| PATCH  | `/api/admin/users/{uid}`    | Admin     | Update plan or unlimited       |
| DELETE | `/api/admin/users/{uid}`    | Admin     | Delete user entirely           |

---

## Notes

- **First run is slow** — downloads ~500MB of ML models (bge-small, BM25, cross-encoder). Cached after first download.
- **CORS** — update `CORS_ORIGINS` in `.env` when changing frontend URL/port (comma-separated).
- **Embeddings are batched** (64 texts/batch) to prevent OOM on large documents.
- **Chunk IDs are stripped** from LLM answers via regex safety net, in case the model leaks them.
- **PDF.js worker** loads from CDN — preview requires internet on first load.
- **Pro = Unlimited** — setting a user to Pro plan automatically sets `is_unlimited=true`. Downgrading to Free sets it to `false`.

---

## License & Copyright

&copy; 2025 Harshit Goyal. All rights reserved.

This software and its source code are proprietary. Unauthorized copying, modification, distribution, or any use of this code, via any medium, is strictly prohibited. This repository is for **viewing and educational purposes only**.
