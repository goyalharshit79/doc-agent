"""
Billing endpoints — create Razorpay subscription + handle webhooks.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import get_current_user_id
from app.services.billing import (
    create_razorpay_subscription,
    get_usage,
    verify_razorpay_webhook,
    handle_razorpay_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing")


class SubscribeRequest(BaseModel):
    email: str


class SubscribeResponse(BaseModel):
    subscription_id: str
    razorpay_key_id: str


# ── POST /billing/subscribe ─────────────────────────────────────────────────

@router.post("/subscribe", response_model=SubscribeResponse)
def subscribe(body: SubscribeRequest, user_id: str = Depends(get_current_user_id)):
    """Create a Razorpay subscription for the authenticated user."""
    try:
        result = create_razorpay_subscription(user_id, body.email)
        return SubscribeResponse(**result)
    except Exception as e:
        logger.exception("Failed to create Razorpay subscription")
        raise HTTPException(status_code=500, detail=f"Subscription creation failed: {str(e)}")


# ── POST /billing/webhook/razorpay ──────────────────────────────────────────

@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """
    Handle Razorpay webhook events.
    No auth required — verified via HMAC signature.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_razorpay_webhook(body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    import json
    payload = json.loads(body)
    event_type = payload.get("event", "")

    try:
        handle_razorpay_event(event_type, payload)
    except Exception as e:
        logger.exception(f"Webhook processing failed for {event_type}")
        # Return 200 anyway — Razorpay retries on non-2xx
        pass

    return {"status": "ok"}
