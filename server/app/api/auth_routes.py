"""
Auth endpoints — signup and login via Supabase Auth.
Supabase handles password hashing, sessions, and JWT issuance.
We just proxy the calls and return the token to the frontend.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from supabase import create_client
from app.core.config import get_settings

router = APIRouter(prefix="/auth")


class AuthRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    user_id: str
    email: str

class RefreshRequest(BaseModel):
    refresh_token: str


def get_supabase():
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_key)


@router.post("/signup", response_model=AuthResponse)
def signup(body: AuthRequest):
    try:
        sb = get_supabase()
        
        res = sb.auth.sign_up({"email": body.email, "password": body.password})

        if not res.user:
            raise HTTPException(status_code=400, detail="Signup failed — user not created")

        # Supabase requires email confirmation by default.
        # For dev, disable it in Supabase dashboard → Auth → Settings → Confirm email.
        if not res.session:
            return AuthResponse(
                access_token="pending_email_confirmation",
                user_id=res.user.id,
                email=res.user.email,
            )

        return AuthResponse(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            user_id=res.user.id,
            email=res.user.email,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=AuthResponse)
def login(body: AuthRequest):
    try:
        sb = get_supabase()
        res = sb.auth.sign_in_with_password({"email": body.email, "password": body.password})

        if not res.session:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        return AuthResponse(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            user_id=res.user.id,
            email=res.user.email,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.post("/refresh", response_model=AuthResponse)
def refresh(body: RefreshRequest):
    try:
        sb = get_supabase()
        res = sb.auth.refresh_session(body.refresh_token)

        if not res.session:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        return AuthResponse(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            user_id=res.user.id,
            email=res.user.email,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ── Forgot / Reset Password ─────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    access_token: str
    new_password: str


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest):
    """Send a password reset email via Supabase."""
    try:
        sb = get_supabase()
        sb.auth.reset_password_email(body.email)
        return {"message": "If that email exists, a reset link has been sent."}
    except Exception:
        # Don't reveal whether the email exists
        return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest):
    """Reset password using the token from the Supabase reset email."""
    try:
        sb = get_supabase()
        # Use the access_token from the reset link to update the password
        user_resp = sb.auth.get_user(body.access_token)
        if not user_resp or not user_resp.user:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")

        res = sb.auth.admin.update_user_by_id(
            user_resp.user.id,
            {"password": body.new_password},
        )
        if not res.user:
            raise HTTPException(status_code=400, detail="Password reset failed")
        return {"message": "Password updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Password reset failed: {str(e)}")
