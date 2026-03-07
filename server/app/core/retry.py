"""
Centralized retry decorator for all GCP / Google Cloud API calls.

Uses exponential backoff with jitter to handle transient failures from:
- Vertex AI Vector Search (upsert, search, delete)
- Google Gemini / Generative AI (generate_content)

Usage:
    from app.core.retry import gcp_retry

    @gcp_retry
    def _call_vertex(index, points):
        index.upsert_datapoints(datapoints=points)
"""

import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log,
)

from google.api_core.exceptions import (
    ServiceUnavailable,
    TooManyRequests,
    InternalServerError,
    DeadlineExceeded,
    ResourceExhausted,
    Aborted,
    GatewayTimeout,
)

logger = logging.getLogger(__name__)

# ── Retryable exception types ────────────────────────────────────────────────
# These are transient GCP errors that are safe to retry.

_RETRYABLE_GCP_EXCEPTIONS = (
    ServiceUnavailable,     # 503
    TooManyRequests,        # 429
    InternalServerError,    # 500
    DeadlineExceeded,       # 504 / timeout
    ResourceExhausted,      # 429 variant (quota)
    Aborted,                # 409 transient
    GatewayTimeout,         # 504
    ConnectionError,        # Network-level failures
    TimeoutError,           # Python-level timeout
)

# ── Retry decorator ──────────────────────────────────────────────────────────

gcp_retry = retry(
    retry=retry_if_exception_type(_RETRYABLE_GCP_EXCEPTIONS),
    stop=stop_after_attempt(4),                    # 1 initial + 3 retries
    wait=wait_exponential_jitter(
        initial=1,      # first wait: ~1 second
        max=10,          # cap at 10 seconds
        jitter=2,        # add up to 2s random jitter
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,        # after all retries exhausted, raise the original exception
)
