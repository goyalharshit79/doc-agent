"""
Billing service — user profile queries, plan limit logic, Razorpay API calls,
and webhook signature verification.
"""

import hashlib
import hmac
import logging
from datetime import date

import httpx
from supabase import create_client

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _get_supabase():
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ── Profile helpers ──────────────────────────────────────────────────────────

def get_user_profile(user_id: str) -> dict:
    """Fetch user_profiles row. Auto-creates if missing (race-safe)."""
    sb = _get_supabase()
    result = sb.table("user_profiles").select("*").eq("user_id", user_id).execute()
    if result.data:
        return result.data[0]

    # Auto-create for users who signed up before the trigger existed
    sb.table("user_profiles").insert({"user_id": user_id}).execute()
    result = sb.table("user_profiles").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else {
        "user_id": user_id, "plan": "free", "is_unlimited": False,
        "queries_today": 0, "query_date": str(date.today()),
    }


def get_document_count(user_id: str) -> int:
    """Count how many documents a user owns."""
    sb = _get_supabase()
    result = sb.table("documents").select("doc_id").eq("user_id", user_id).execute()
    return len(result.data) if result.data else 0


def get_plan_limits(plan: str) -> dict:
    """Return limits for a given plan."""
    settings = get_settings()
    if plan == "pro":
        return {
            "max_documents": settings.pro_max_documents,
            "max_queries_per_day": None,  # unlimited
        }
    return {
        "max_documents": settings.free_max_documents,
        "max_queries_per_day": settings.free_max_queries_per_day,
    }


def get_usage(user_id: str) -> dict:
    """Return full usage info for the frontend."""
    profile = get_user_profile(user_id)
    doc_count = get_document_count(user_id)
    limits = get_plan_limits(profile["plan"])

    # Reset daily counter if date rolled over
    queries_today = profile["queries_today"]
    if str(profile["query_date"]) != str(date.today()):
        queries_today = 0

    return {
        "plan": profile["plan"],
        "is_unlimited": profile["is_unlimited"],
        "documents_used": doc_count,
        "documents_limit": limits["max_documents"],
        "queries_used": queries_today,
        "queries_limit": limits["max_queries_per_day"],
        "subscription_status": profile.get("subscription_status", "none"),
    }


# ── Query counter ────────────────────────────────────────────────────────────

def increment_query_count(user_id: str):
    """Increment the daily query counter. Resets if date changed."""
    sb = _get_supabase()
    profile = get_user_profile(user_id)
    today = str(date.today())

    if str(profile["query_date"]) != today:
        # New day — reset counter
        sb.table("user_profiles").update({
            "queries_today": 1,
            "query_date": today,
        }).eq("user_id", user_id).execute()
    else:
        sb.table("user_profiles").update({
            "queries_today": profile["queries_today"] + 1,
        }).eq("user_id", user_id).execute()


# ── Razorpay API ─────────────────────────────────────────────────────────────

def create_razorpay_subscription(user_id: str, email: str) -> dict:
    """Create a Razorpay subscription for the user."""
    settings = get_settings()

    auth = (settings.razorpay_key_id, settings.razorpay_key_secret)

    # Step 1: Create or get customer
    profile = get_user_profile(user_id)
    customer_id = profile.get("razorpay_customer_id")

    if not customer_id:
        resp = httpx.post(
            "https://api.razorpay.com/v1/customers",
            auth=auth,
            json={"email": email, "notes": {"user_id": user_id}},
        )
        resp.raise_for_status()
        customer_id = resp.json()["id"]
        # Save customer ID
        sb = _get_supabase()
        sb.table("user_profiles").update({
            "razorpay_customer_id": customer_id,
        }).eq("user_id", user_id).execute()

    # Step 2: Create subscription
    resp = httpx.post(
        "https://api.razorpay.com/v1/subscriptions",
        auth=auth,
        json={
            "plan_id": settings.razorpay_plan_id,
            "customer_id": customer_id,
            "total_count": 120,  # max billing cycles
            "notes": {"user_id": user_id},
        },
    )
    resp.raise_for_status()
    sub_data = resp.json()

    # Save subscription ID
    sb = _get_supabase()
    sb.table("user_profiles").update({
        "razorpay_subscription_id": sub_data["id"],
        "subscription_status": sub_data.get("status", "created"),
    }).eq("user_id", user_id).execute()

    return {
        "subscription_id": sub_data["id"],
        "razorpay_key_id": settings.razorpay_key_id,
    }


# ── Razorpay webhook ─────────────────────────────────────────────────────────

def verify_razorpay_webhook(body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook signature using HMAC SHA256."""
    settings = get_settings()
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def handle_razorpay_event(event_type: str, payload: dict):
    """Process a Razorpay webhook event."""
    sb = _get_supabase()

    # Log the event
    sb.table("razorpay_events").insert({
        "event_type": event_type,
        "payload": payload,
    }).execute()

    # Extract subscription info
    entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
    subscription_id = entity.get("id")

    if not subscription_id:
        logger.warning(f"Razorpay webhook {event_type}: no subscription_id found")
        return

    # Find the user with this subscription
    result = sb.table("user_profiles").select("user_id").eq(
        "razorpay_subscription_id", subscription_id
    ).execute()

    if not result.data:
        logger.warning(f"Razorpay webhook: no user for subscription {subscription_id}")
        return

    user_id = result.data[0]["user_id"]
    status = entity.get("status", "")

    if event_type == "subscription.activated":
        sb.table("user_profiles").update({
            "plan": "pro",
            "is_unlimited": True,
            "subscription_status": "active",
        }).eq("user_id", user_id).execute()
        logger.info(f"User {user_id} upgraded to Pro (unlimited)")

    elif event_type == "subscription.charged":
        sb.table("user_profiles").update({
            "subscription_status": "active",
        }).eq("user_id", user_id).execute()

    elif event_type in ("subscription.cancelled", "subscription.completed", "subscription.expired"):
        sb.table("user_profiles").update({
            "plan": "free",
            "is_unlimited": False,
            "subscription_status": status or "cancelled",
        }).eq("user_id", user_id).execute()
        logger.info(f"User {user_id} downgraded to Free ({event_type})")

    elif event_type == "subscription.halted":
        sb.table("user_profiles").update({
            "subscription_status": "halted",
        }).eq("user_id", user_id).execute()
        logger.warning(f"User {user_id} subscription halted")

    elif event_type == "subscription.pending":
        sb.table("user_profiles").update({
            "subscription_status": "pending",
        }).eq("user_id", user_id).execute()

    else:
        logger.info(f"Razorpay webhook: unhandled event {event_type}")
