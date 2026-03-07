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
