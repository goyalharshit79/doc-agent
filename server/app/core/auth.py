"""
Auth middleware — verifies Supabase JWT by calling Supabase's auth.getUser().
This delegates verification to Supabase itself, so it works correctly
regardless of signing algorithm (HS256 / RS256) and handles expiry automatically.
"""

import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import create_client

from app.core.config import get_settings

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()

# Reuse a single Supabase admin client for token verification
_supabase_client = None


def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    Dependency — verifies the Supabase JWT by calling Supabase's auth endpoint.
    Returns the user_id (UUID string) on success.
    Raises 401 on any failure.
    """
    token = credentials.credentials

    try:
        sb = _get_supabase()
        user_response = sb.auth.get_user(token)

        if not user_response or not user_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: could not resolve user",
            )

        user_id = user_response.user.id
        logger.info(f"Authenticated user: {user_id}")
        return user_id

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Auth failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
        )
