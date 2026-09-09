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
from .command_service import get_command_service, CommandStatus
from . import command_defs
from .rate_limit import is_rate_limited, login_rate_limiter, command_rate_limiter, export_rate_limiter

router = APIRouter(prefix="/api", tags=["api"])


def _get_templates(request: Request):
    """Get Jinja2Templates from app state."""
    return request.app.state.templates


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
    templates = _get_templates(request)
    return templates.TemplateResponse(request, name, context)


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
    # Rate limiting for login attempts
    ip_key = f"ip:{request.client.host}" if request.client else "unknown"
    if is_rate_limited(ip_key, login_rate_limiter):
        # Small delay to avoid timing attacks, then generic error
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
    
    form_data = await request.form()
    username = form_data.get("username", "")
    password = form_data.get("password", "")
    
    user = authenticate_user(username, password)
    if user is None:
        # Record the failed attempt and re-show login with error
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


# ── Telescope Command Endpoints ──────────────────────────────────────────
# These endpoints route commands through the CommandService which validates,
# checks safety, and forwards to the STCS V1 control layer via WebSocket.

def _get_current_user_or_401(request: Request):
    """Get current user or raise 401."""
    user = auth.get_current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def _validate_csrf_or_403(form_data, request: Request):
    """Validate CSRF token or raise 403."""
    if not _csrf_validate_form(form_data, request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def _command_response(result):
    """Convert CommandService result to standardized JSON response."""
    return {
        "status": result.status.value,
        "command": result.command,
        "message": result.message,
        "executed": result.executed,
        "reason": result.reason,
        "details": result.details,
        "timestamp": result.timestamp,
    }


@router.post("/command/manual", include_in_schema=False)
async def command_manual(request: Request):
    """Manual RA/DEC jog command (held signal)."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    svc = get_command_service()
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command="manual_move",
        fields={
            "axis": form_data.get("axis", "").upper(),
            "direction": form_data.get("direction", "").upper(),
            "speed": form_data.get("speed", "").upper(),
        }
    )
    return _command_response(result)


@router.post("/command/stop", include_in_schema=False)
async def command_stop(request: Request):
    """Emergency stop all motion."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    svc = get_command_service()
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command="stop",
        fields={}
    )
    return _command_response(result)


@router.post("/command/tracking", include_in_schema=False)
async def command_tracking(request: Request):
    """Tracking ON/OFF command."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    action = form_data.get("action", "").lower()  # "on" or "off"
    if action not in ("on", "off"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action must be 'on' or 'off'")
    
    svc = get_command_service()
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command="tracking_on" if action == "on" else "tracking_off",
        fields={}
    )
    return _command_response(result)


@router.post("/command/dome", include_in_schema=False)
async def command_dome(request: Request):
    """Dome CW/CCW/OFF command."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    action = form_data.get("action", "").upper()  # "CW", "CCW", "OFF"
    if action not in ("CW", "CCW", "OFF"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action must be CW, CCW, or OFF")
    
    cmd_map = {"CW": "dome_cw", "CCW": "dome_ccw", "OFF": "dome_off"}
    
    svc = get_command_service()
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command=cmd_map[action],
        fields={}
    )
    return _command_response(result)


@router.post("/command/slew", include_in_schema=False)
async def command_slew(request: Request):
    """Go-To slew command (requires control lock)."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    # Check control lock for slew commands
    svc = get_command_service()
    lock = svc.get_control_lock_status()
    if lock["owner"] and lock["owner"] != user["username"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Control lock held by {lock['owner']} — acquire it first"
        )
    
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command="slewtocoordinatesasync",
        fields={}
    )
    return _command_response(result)


@router.post("/command/park", include_in_schema=False)
async def command_park(request: Request):
    """Park telescope at home position (requires control lock)."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    svc = get_command_service()
    lock = svc.get_control_lock_status()
    if lock["owner"] and lock["owner"] != user["username"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Control lock held by {lock['owner']} — acquire it first"
        )
    
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command="park",
        fields={}
    )
    return _command_response(result)


@router.post("/command/calibration", include_in_schema=False)
async def command_calibration(request: Request):
    """Calibration commands (sync, clear offsets) - requires control lock."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    action = form_data.get("action", "").lower()  # "sync", "clear_offsets"
    if action not in ("sync", "clear_offsets"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action must be 'sync' or 'clear_offsets'")
    
    svc = get_command_service()
    lock = svc.get_control_lock_status()
    if lock["owner"] and lock["owner"] != user["username"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Control lock held by {lock['owner']} — acquire it first"
        )
    
    cmd_map = {"sync": "synccalibration", "clear_offsets": "clear_offsets"}
    
    # Pass sync parameters if provided
    fields = {}
    if action == "sync":
        ra_hms = form_data.get("ra_hms", "").strip()
        dec_dms = form_data.get("dec_dms", "").strip()
        dome_az = form_data.get("dome_az", "").strip()
        if ra_hms:
            fields["ra_hms"] = ra_hms
        if dec_dms:
            fields["dec_dms"] = dec_dms
        if dome_az:
            fields["dome_az"] = dome_az
    
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command=cmd_map[action],
        fields=fields
    )
    return _command_response(result)


@router.post("/command/emergency-stop", include_in_schema=False)
async def command_emergency_stop(request: Request):
    """Emergency stop - highest priority, always allowed for authenticated users."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    svc = get_command_service()
    result = svc.execute(
        username=user["username"],
        role=user["role"],
        command="emergency_stop",
        fields={}
    )
    return _command_response(result)


@router.get("/command/lock/status", include_in_schema=False)
async def command_lock_status(request: Request):
    """Get current control lock status."""
    user = _get_current_user_or_401(request)
    svc = get_command_service()
    return svc.get_control_lock_status()


@router.post("/command/lock/acquire", include_in_schema=False)
async def command_lock_acquire(request: Request):
    """Acquire control lock for slew/calibration commands."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    svc = get_command_service()
    ok, reason = svc.acquire_control_lock(user["username"])
    return {"ok": ok, "reason": reason}


@router.post("/command/lock/release", include_in_schema=False)
async def command_lock_release(request: Request):
    """Release control lock."""
    user = _get_current_user_or_401(request)
    form_data = await request.form()
    _validate_csrf_or_403(form_data, request)
    
    svc = get_command_service()
    ok = svc.release_control_lock(user["username"], user["role"])
    return {"ok": ok}


@router.get("/command/status", include_in_schema=False)
async def command_status(request: Request):
    """Get command service status (enabled/disabled)."""
    user = _get_current_user_or_401(request)
    svc = get_command_service()
    client = svc.client
    return {
        "commands_enabled": svc.commands_enabled,
        "stcs_connected": client.is_connected,
        "client_stats": client.get_stats(),
        "control_lock": svc.get_control_lock_status(),
    }