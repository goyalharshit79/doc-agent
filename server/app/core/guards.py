"""
Plan-limit guards — FastAPI dependencies that check upload/query limits.
Drop-in replacements for get_current_user_id (they return user_id on success).
"""

import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import get_current_user_id
from app.services.billing import get_user_profile, get_document_count, get_plan_limits

from datetime import date

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()


def check_upload_limit(
    user_id: str = Depends(get_current_user_id),
) -> str:
    """
    Dependency — verifies the user hasn't exceeded their document upload limit.
    Returns user_id on success, raises 403 on limit reached.
    """
    profile = get_user_profile(user_id)

    # Unlimited users bypass all limits
    if profile.get("is_unlimited"):
        return user_id

    plan = profile.get("plan", "free")
    limits = get_plan_limits(plan)
    doc_count = get_document_count(user_id)

    if doc_count >= limits["max_documents"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "DOCUMENT_LIMIT",
                "message": f"You've reached the {plan} plan limit of {limits['max_documents']} document{'s' if limits['max_documents'] != 1 else ''}. Upgrade to Pro for more.",
                "current": doc_count,
                "limit": limits["max_documents"],
                "plan": plan,
            },
        )

    return user_id


def check_query_limit(
    user_id: str = Depends(get_current_user_id),
) -> str:
    """
    Dependency — verifies the user hasn't exceeded their daily query limit.
    Returns user_id on success, raises 429 on limit reached.
    """
    profile = get_user_profile(user_id)

    # Unlimited users bypass all limits
    if profile.get("is_unlimited"):
        return user_id

    plan = profile.get("plan", "free")
    limits = get_plan_limits(plan)

    # Pro users have unlimited queries
    if limits["max_queries_per_day"] is None:
        return user_id

    # Check daily counter — reset if date changed
    queries_today = profile.get("queries_today", 0)
    query_date = str(profile.get("query_date", ""))
    today = str(date.today())

    if query_date != today:
        queries_today = 0  # New day, counter resets

    if queries_today >= limits["max_queries_per_day"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "QUERY_LIMIT",
                "message": f"You've used all {limits['max_queries_per_day']} questions for today. Upgrade to Pro for unlimited questions.",
                "current": queries_today,
                "limit": limits["max_queries_per_day"],
                "plan": plan,
            },
        )

    return user_id
