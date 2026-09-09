"""
Authentication module for the STCS Web Application Phase 1.

Handles user authentication, password hashing/verification, session management,
and role-based access control. All passwords are hashed using bcrypt;
plaintext passwords are never stored.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status

from .database import (
    get_user_by_username,
    get_user_by_id,
    verify_password,
)


# ── Session configuration ─────────────────────────────────────────────────
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
    async def dependency(current_user: dict = Depends(get_current_user)):
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        if current_user["role"] not in allowed_roles:
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