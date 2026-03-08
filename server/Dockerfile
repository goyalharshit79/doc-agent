# ── DocAgent API — Cloud Run Dockerfile ──────────────────────────────────────
# Multi-stage build for smaller final image.

FROM python:3.11-slim AS base

# System deps required by unstructured (PDF/DOCX parsing), ONNX Runtime, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    poppler-utils \
    tesseract-ocr \
    libxml2-dev \
    libxslt1-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install Python dependencies ─────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Copy application code ───────────────────────────────────────────────────
COPY . .

# ── Runtime config ──────────────────────────────────────────────────────────
# Cloud Run injects PORT env var (default 8080).
ENV PORT=8080
EXPOSE ${PORT}

# Run with uvicorn — Cloud Run sends SIGTERM for graceful shutdown.
CMD exec uvicorn main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers 1 \
    --timeout-keep-alive 120
