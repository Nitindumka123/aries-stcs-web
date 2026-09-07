"""
Authentication module for the STCS Web Application Phase 1.

Handles user authentication, password hashing/verification, session management,
and role-based access control. All passwords are hashed using SHA256 with a
random salt; plaintext passwords are never stored.
"""

import json
import os
import secrets
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates

from .database import (
    create_user,
    get_user_by_username,
    get_user_by_id,
    init_users_table,
    verify_password,
)


# ── OAuth2 bearer for token-based auth ──────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# ── Jinja2 templates ────────────────────────────────────────────────────
templates = Jinja2Templates(directory="stcs_web/templates")


def _display_state(value):
    """Operator-friendly words for internal telemetry states (see main.py)."""
    return {
        "LIVE": "Live",
        "STALE": "Stale",
        "NOT_CONNECTED": "Disconnected",
        "NOT_AVAILABLE": "Not available",
        "UNKNOWN": "Unknown",
    }.get(value, value)


templates.env.filters["disp"] = _display_state


def _age(value):
    """Format an epoch timestamp as a short relative age (see main.py)."""
    try:
        import time as _time
        age = _time.time() - float(value)
    except (TypeError, ValueError):
        return "—"
    if age < 0:
        return "—"
    if age < 90:
        return f"{age:.0f}s ago"
    if age < 5400:
        return f"{age / 60:.0f}m ago"
    if age < 86400 * 30:
        return f"{age / 3600:.1f}h ago"
    return "—"


templates.env.filters["age"] = _age

# ── Session middleware ──────────────────────────────────────────────────
# Session cookie name and secret key
SESSION_COOKIE_NAME = "stcs_session"
SESSION_SECRET = os.environ.get("SESSION_SECRET", secrets.token_hex(32))

# Session lifetime (minutes) — single source of truth for login_user().
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))

# ── Authentication helpers ──────────────────────────────────────────────
def authenticate_user(username: str, password: str) -> dict | None:
    """Authenticate a user by username and password.
    
    Returns user dict if authentication succeeds, None otherwise.
    """
    user = get_user_by_username(username)
    if user is None:
        return None
    if not user["is_active"]:
        return None
    if not verify_password(user["password_hash"], password):
        return None
    return user


# NOTE: verify_password is imported from .database (bcrypt). The old local
# SHA256 copy was removed because it shadowed the import and would reject
# every bcrypt-hashed password, breaking all logins.


def create_access_token(user: dict) -> str:
    """Create a JWT-like session token for the user.
    
    Token format includes: user_id, username, role, expiration
    The token is signed with the session secret.
    """
    expiration = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    token_data = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "exp": expiration,
        "iat": datetime.now(timezone.utc),
    }
    # Simple base64url-encoded JWT-like token
    # In production, use PyJWT or similar
    import base64
    import json
    
    payload_json = json.dumps(token_data)
    token_bytes = payload_json.encode("utf-8")
    token_b64 = base64.urlsafe_b64encode(token_bytes).decode("utf-8")
    # Include a simple HMAC-like signature for demo purposes
    import hmac
    key = os.environ.get("SESSION_SECRET", "stcs-secret-key-change-in-production").encode()
    signature = hmac.new(key, token_bytes, "sha256").digest()
    token_b64 += "." + base64.urlsafe_b64encode(signature).decode("utf-8")
    
    return token_b64


def decode_access_token(token: str) -> dict | None:
    """Decode and verify a session token.
    
    Returns user payload dict if valid, None if invalid/expired.
    """
    try:
        import base64
        import hmac
        import json
        
        parts = token.split(".")
        if len(parts) != 3:
            return None
        
        payload_b64, _, sig_b64 = parts
        
        # Verify signature
        key = os.environ.get("SESSION_SECRET", "stcs-secret-key-change-in-production").encode()
        expected_sig = hmac.new(key, base64.urlsafe_b64decode(payload_b64 + "=="), "sha256").digest()
        actual_sig = base64.urlsafe_b64decode(sig_b64 + "==")
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        
        # Decode payload
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8")
        payload = json.loads(payload_json)
        
        # Check expiration
        exp = payload.get("exp")
        if exp and datetime.now(timezone.utc) > datetime.fromtimestamp(exp, tz=timezone.utc):
            return None
        
        return payload
    except Exception:
        return None


def get_current_user(request: Request) -> dict | None:
    """Get the current authenticated user from the request session.
    
    Returns user dict or None if not authenticated.
    """
    session_data = request.session.get("stcs_user")
    if session_data is None:
        return None
    
    # Check session expiration
    expires_str = session_data.get("expires_at")
    if expires_str:
        try:
            expires_at = datetime.fromisoformat(expires_str)
            if datetime.now(timezone.utc) > expires_at:
                # Session expired
                request.session.pop("stcs_user", None)
                return None
        except (ValueError, TypeError):
            request.session.pop("stcs_user", None)
            return None
    
    user_id = session_data.get("user_id")
    if user_id is None:
        request.session.pop("stcs_user", None)
        return None
    
    user = get_user_by_id(user_id)
    if user is None:
        request.session.pop("stcs_user", None)
        return None
    
    # Update last activity
    from .database import update_user_activity
    update_user_activity(user_id)
    
    return user


def login_user(request: Request, user: dict):
    """Log in a user by setting session data."""
    expiration = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    request.session["stcs_user"] = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "expires_at": expiration.isoformat(),
    }


def logout_user(request: Request):
    """Log out a user by clearing session data."""
    request.session.pop("stcs_user", None)


# Role checking dependencies
def require_role(allowed_roles: list[str]):
    """Dependency factory that returns a FastAPI dependency to check user role.
    
    Args:
        allowed_roles: List of role strings that are allowed to access the endpoint.
    
    Returns: FastAPI dependency function.
    """
    from fastapi import Depends
    
    async def dependency(current_user: dict = Depends(get_current_user)):
        if current_user is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if current_user["role"] not in allowed_roles:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user['role']}' not authorized. Required one of: {allowed_roles}",
            )
        return current_user
    return dependency


# Convenience dependencies
def require_admin(current_user: dict = Depends(get_current_user)):
    """FastAPI dependency that requires the user to be an Admin."""
    return require_role(["admin"])(current_user)


def require_scientist(current_user: dict = Depends(get_current_user)):
    """FastAPI dependency that requires the user to be a Scientist (or admin)."""
    return require_role(["scientist", "admin"])(current_user)


# ── FastAPI app creation ────────────────────────────────────────────────
def create_app() -> FastAPI:
    """Create and configure the FastAPI application.
    
    Returns the configured FastAPI instance.
    """
    app = FastAPI(
        title="ARIES STCS Modernization",
        description="Modern web application for the 104 cm Sampurnanand Telescope",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    
    # Add session middleware (Starlette>=1.x uses `session_cookie`)
    app.add_middleware(
        SessionMiddleware,
        session_cookie=SESSION_COOKIE_NAME,
        secret_key=SESSION_SECRET,
    )
    
    # Include routes
    from . import routes
    app.include_router(routes.router, prefix="/api", tags=["api"])
    
    # Add startup event
    @app.on_event("startup")
    async def startup_event():
        init_users_table()
        _ensure_default_users()
    
    return app


def _ensure_default_users():
    """Ensure default development users exist in the database.
    
    Usernames and passwords are read from environment variables.
    Development credentials only - never use in production without proper hashing.
    """
    import os
    
    admin_username = os.environ.get("ADMIN_USERNAME", "Admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")
    
    scientist_username = os.environ.get("SCIENTIST_USERNAME", "Scientist1")
    scientist_password = os.environ.get("SCIENTIST_PASSWORD", "Pass@123")
    
    # Check if admin exists
    admin = get_user_by_username(admin_username)
    if admin is None:
        create_user(admin_username, admin_password, role="admin")
        print(f"Created default admin user: {admin_username}")
    
    # Check if scientist exists
    scientist = get_user_by_username(scientist_username)
    if scientist is None:
        create_user(scientist_username, scientist_password, role="scientist")
        print(f"Created default scientist user: {scientist_username}")