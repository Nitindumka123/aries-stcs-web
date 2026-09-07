from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
import secrets

from . import auth
from .auth import (
    authenticate_user,
    get_current_user,
    login_user,
    logout_user,
    require_admin,
    require_scientist,
)
from .database import create_user, get_db_connection, get_user_by_username

router = APIRouter(prefix="/api", tags=["api"])


# ── CSRF helper ───────────────────────────────────────────────────────────
def _csrf_token(request: Request) -> str:
    """Get or generate a CSRF token for the current session."""
    token = request.session.get("_stcs_csrf_token")
    if token is None:
        token = secrets.token_hex(32)
        request.session["_stcs_csrf_token"] = token
    return token


def _csrf_validate_form(form, request: Request) -> bool:
    """Validate CSRF token from an already-parsed form against the session.

    WHY parsed-form input: request.form() is a coroutine in Starlette and
    must be awaited by the caller first; this helper compares values only.
    """
    try:
        form_token = (form.get("_stcs_csrf_token", "") or "").strip()
    except Exception:
        return False
    session_token = (request.session.get("_stcs_csrf_token", "") or "").strip()
    if not form_token or not session_token:
        return False
    import hmac
    return hmac.compare_digest(form_token, session_token)


def _csrf_validate(request: Request) -> bool:
    """Legacy sync wrapper (no parsed form available) — always False.

    Kept so older call sites fail closed instead of silently passing.
    Callers must parse the form with 'await request.form()' and use
    _csrf_validate_form().
    """
    return False


# ── HTML template rendering helpers ───────────────────────────────────────
def template_response(name: str, request: Request, **context) -> HTMLResponse:
    """Render a Jinja2 template with the request context.

    NOTE: installed Starlette 1.6.0 uses TemplateResponse(request, name,
    context) — request first. Verified against this environment.
    """
    return auth.templates.TemplateResponse(request, name, context)


# ── Login route ─────────────────────────────────────────────────────────
@router.get("/login", include_in_schema=False)
async def login_get(request: Request):
    """Show the login page."""
    # If already authenticated, redirect to the observatory shell
    user = auth.get_current_user(request)
    if user is not None:
        return RedirectResponse(url="/app/control")
    # Generate CSRF token for this session
    token = _csrf_token(request)
    return template_response("login.html", request, csrf_token=token)


@router.post("/login", include_in_schema=False)
async def login_post(request: Request, response: Response):
    """Process login form submission."""
    form_data = await request.form()
    username = form_data.get("username", "")
    password = form_data.get("password", "")
    
    user = authenticate_user(username, password)
    if user is None:
        # Re-show login with error (fresh CSRF token so retry works)
        return template_response(
            "login.html",
            request,
            error="Invalid username or password.",
            csrf_token=_csrf_token(request),
        )
    
    # Validate CSRF token (parsed form) before processing login
    if not _csrf_validate_form(form_data, request):
        token = _csrf_token(request)
        return template_response(
            "login.html",
            request,
            error="Invalid CSRF token. Please try logging in again.",
            csrf_token=token,
        )

    login_user(request, user)
    
    # Redirect to the Phase 2 observatory shell
    return RedirectResponse(url="/app/control", status_code=status.HTTP_302_FOUND)


# ── Registration route (for initial setup) ──────────────────────────────
@router.post("/register", include_in_schema=False)
async def register(request: Request):
    """Register a new user."""
    form_data = await request.form()
    username = form_data.get("username", "").strip()
    password = form_data.get("password", "")
    role = form_data.get("role", "scientist")
    
    if not username or not password:
        return template_response(
            "login.html",
            request,
            error="Username and password are required.",
        )
    
    try:
        create_user(username, password, role=role)
    except ValueError as e:
        return template_response(
            "login.html",
            request,
            error=str(e),
        )
    
    # Log in the newly registered user
    user = get_user_by_username(username)
    login_user(request, user)
    
    return RedirectResponse(url="/api/dashboard", status_code=status.HTTP_302_FOUND)


# ── Logout route ────────────────────────────────────────────────────────
@router.post("/logout", include_in_schema=False)
async def logout(request: Request, response: Response):
    """Log out the current user."""
    # Validate CSRF token (parsed form) before logging out
    form_data = await request.form()
    if not _csrf_validate_form(form_data, request):
        token = _csrf_token(request)
        return template_response(
            "login.html",
            request,
            error="Invalid CSRF token. Please try again.",
            csrf_token=token,
        )
    logout_user(request)
    response = RedirectResponse(url="/api/login", status_code=status.HTTP_302_FOUND)
    return response


# ── Auth check route ────────────────────────────────────────────────────
@router.get("/auth/check", include_in_schema=False)
async def auth_check(request: Request):
    """Check if user is authenticated and return user info."""
    user = auth.get_current_user(request)
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": user["username"],
        "role": user["role"],
    }


# ── Dashboard route ─────────────────────────────────────────────────────
@router.get("/dashboard", include_in_schema=False)
async def dashboard(request: Request):
    """Legacy dashboard URL → canonical observatory shell.

    WHY redirect: the Phase 2 CONTROL console (/app/control) replaced the
    old dashboard template, so one canonical shell avoids UI drift.
    """
    return RedirectResponse(url="/app/control", status_code=status.HTTP_302_FOUND)


# ── Users API (for admin) ───────────────────────────────────────────────
@router.get("/users", include_in_schema=False)
async def list_users(request: Request):
    """List all users (admin only)."""
    user = auth.get_current_user(request)
    if user is None or user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, role, is_active, created_at FROM users ORDER BY username"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    
    users = []
    for row in rows:
        users.append(
            {
                "id": row[0],
                "username": row[1],
                "role": row[2],
                "is_active": row[3],
                "created_at": str(row[4]) if row[4] else None,
            }
        )
    return {"users": users}