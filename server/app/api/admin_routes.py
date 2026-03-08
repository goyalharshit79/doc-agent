"""
Admin endpoints — user management, accessible only by admin email.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.core.auth import get_current_user_id
from app.core.config import get_settings
from app.services.billing import _get_supabase

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


# ── Admin guard ──────────────────────────────────────────────────────────────

def _get_admin_user_id(user_id: str = Depends(get_current_user_id)) -> str:
    """Verify the caller is the admin. Returns user_id or raises 403."""
    sb = _get_supabase()
    settings = get_settings()

    # Look up the user's email from Supabase auth
    try:
        user = sb.auth.admin.get_user_by_id(user_id)
        email = user.user.email if user and user.user else None
    except Exception as e:
        logger.warning(f"Admin check failed: {e}")
        raise HTTPException(status_code=403, detail="Access denied")

    if email != settings.admin_email:
        raise HTTPException(status_code=403, detail="Access denied")

    return user_id


# ── Schemas ──────────────────────────────────────────────────────────────────

class AdminUserUpdate(BaseModel):
    plan: Optional[str] = None
    is_unlimited: Optional[bool] = None


# ── GET /admin/users ─────────────────────────────────────────────────────────

@router.get("/users")
def list_all_users(_admin: str = Depends(_get_admin_user_id)):
    """List all users with their profile data and document counts."""
    sb = _get_supabase()

    # Get all auth users
    try:
        auth_users_response = sb.auth.admin.list_users()
        # Handle different response formats
        if hasattr(auth_users_response, '__iter__'):
            auth_users = list(auth_users_response)
        else:
            auth_users = auth_users_response
    except Exception as e:
        logger.exception("Failed to list auth users")
        raise HTTPException(status_code=500, detail=f"Failed to list users: {str(e)}")

    # Get all profiles
    profiles_result = sb.table("user_profiles").select("*").execute()
    profiles_map = {p["user_id"]: p for p in (profiles_result.data or [])}

    # Get document counts per user
    docs_result = sb.table("documents").select("user_id").execute()
    doc_counts = {}
    for d in (docs_result.data or []):
        uid = d["user_id"]
        doc_counts[uid] = doc_counts.get(uid, 0) + 1

    # Build response
    users = []
    for u in auth_users:
        uid = u.id
        profile = profiles_map.get(uid, {})
        users.append({
            "user_id": uid,
            "email": u.email,
            "created_at": str(u.created_at) if u.created_at else None,
            "plan": profile.get("plan", "free"),
            "is_unlimited": profile.get("is_unlimited", False),
            "subscription_status": profile.get("subscription_status", "none"),
            "document_count": doc_counts.get(uid, 0),
        })

    return users


# ── PATCH /admin/users/{user_id} ─────────────────────────────────────────────

@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: AdminUserUpdate,
    _admin: str = Depends(_get_admin_user_id),
):
    """Update a user's plan or unlimited status."""
    sb = _get_supabase()

    update_data = {}
    if body.plan is not None:
        if body.plan not in ("free", "pro"):
            raise HTTPException(status_code=400, detail="Plan must be 'free' or 'pro'")
        update_data["plan"] = body.plan
        # Pro plan always gets unlimited; downgrade to free removes it
        update_data["is_unlimited"] = (body.plan == "pro")
    if body.is_unlimited is not None and body.plan is None:
        # Only honour explicit is_unlimited toggle when plan isn't being changed
        update_data["is_unlimited"] = body.is_unlimited

    if not update_data:
        raise HTTPException(status_code=400, detail="Nothing to update")

    try:
        sb.table("user_profiles").update(update_data).eq("user_id", user_id).execute()
        return {"message": "User updated", "user_id": user_id, **update_data}
    except Exception as e:
        logger.exception(f"Failed to update user {user_id}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


# ── DELETE /admin/users/{user_id} ────────────────────────────────────────────

@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    _admin: str = Depends(_get_admin_user_id),
):
    """Delete a user completely: auth + profile + documents + vectors."""
    sb = _get_supabase()
    settings = get_settings()

    # Don't allow deleting the admin
    try:
        user = sb.auth.admin.get_user_by_id(user_id)
        if user and user.user and user.user.email == settings.admin_email:
            raise HTTPException(status_code=400, detail="Cannot delete admin user")
    except HTTPException:
        raise
    except Exception:
        pass

    try:
        # 1. Delete document vectors from Vertex AI
        from app.services.vector_store import delete_document_full
        docs = sb.table("documents").select("doc_id").eq("user_id", user_id).execute()
        for doc in (docs.data or []):
            try:
                delete_document_full(doc["doc_id"], user_id)
            except Exception as e:
                logger.warning(f"Failed to delete vectors for {doc['doc_id']}: {e}")

        # 2. Delete user profile (cascade would handle this, but be explicit)
        sb.table("user_profiles").delete().eq("user_id", user_id).execute()

        # 3. Delete from Supabase auth
        sb.auth.admin.delete_user(user_id)

        logger.info(f"Admin deleted user {user_id}")
        return {"message": "User deleted", "user_id": user_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to delete user {user_id}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
