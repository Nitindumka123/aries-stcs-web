"""
STCS Web Application - Phase 2
Modern web observatory application for the 104 cm Sampurnanand Telescope.

Provides authentication, authorization, professional workspaces
(CONTROL / OBSERVATIONS / CAMERA / SYSTEM / ADMIN), and REAL
read-only telemetry integration (Alpaca HTTP, weather UDP, STCS config).

Command intents are validated server-side but never executed against
physical hardware during development/testing (STCS_COMMANDS_ENABLED=0).
The existing STCS V1 desktop application is untouched.
"""

import os
import sys
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Path layout: STCS_WEB_DIR = .../GUI/stcs_web, PROJECT_ROOT = .../GUI.
# WHY two names: templates/static/fallback files live under stcs_web/,
# while imports need the project root on sys.path.
STCS_WEB_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = STCS_WEB_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Database initialization ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from stcs_web import database
    try:
        database.init_users_table()
        print("Database initialized (or not available - using fallback)")
    except Exception as e:
        print(f"Warning: Database initialization unavailable: {e}")
    try:
        from stcs_web import obs_store as _obs
        if _obs.init_obs_tables():
            print("Observation/audit tables ready")
        else:
            print("Observation store unavailable - history shows empty state")
    except Exception as e:
        print(f"Warning: observation store init unavailable: {e}")

    # Create default development users in PostgreSQL if available
    import os
    admin_username = os.environ.get("ADMIN_USERNAME", "Admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")
    scientist_username = os.environ.get("SCIENTIST_USERNAME", "Scientist1")
    scientist_password = os.environ.get("SCIENTIST_PASSWORD", "Pass@123")

    db_available = False
    try:
        admin = database.get_user_by_username(admin_username)
        if admin is None:
            database.create_user(admin_username, admin_password, role="admin")
            print(f"Created default admin user: {admin_username}")
        scientist = database.get_user_by_username(scientist_username)
        if scientist is None:
            database.create_user(scientist_username, scientist_password, role="scientist")
            print(f"Created default scientist user: {scientist_username}")
        db_available = True
    except Exception as e:
        print(f"Warning: Could not create default users in PostgreSQL: {e}")

    # Fall back to file-based credentials only when PostgreSQL is unavailable
    # and development mode is explicitly enabled.
    if not db_available:
        _dev_mode = os.environ.get("DEVELOPMENT_MODE", "").lower() == "true"
        if _dev_mode:
            try:
                from stcs_web.database import hash_password
                hashed_admin = hash_password(admin_password)
                hashed_scientist = hash_password(scientist_password)
                fallback_file = os.path.join(str(STCS_WEB_DIR), "fallback_creds.txt")
                with open(fallback_file, "w") as f:
                    f.write(f"{admin_username}:{hashed_admin}:admin\n")
                    f.write(f"{scientist_username}:{hashed_scientist}:scientist\n")
                print(f"Fallback credentials stored at {fallback_file}")
            except Exception as e:
                print(f"Warning: Could not create fallback credentials: {e}")
        else:
            print("Note: Fallback credentials not created (DEVELOPMENT_MODE not set). "
                  "PostgreSQL is required for authentication.")

    # Start command service (connects to STCS V1 WebSocket control server)
    try:
        from stcs_web.command_service import start_command_service
        start_command_service()
        print("Command service started (STCS V1 WebSocket control client)")
    except Exception as e:
        print(f"Warning: Could not start command service: {e}")

    # Initialize camera schema migrations
    try:
        from stcs_web.obs_store import migrate_camera_schema
        if migrate_camera_schema():
            print("Camera schema migrations applied")
        else:
            print("Camera schema migration skipped (no PostgreSQL)")
    except Exception as e:
        print(f"Warning: Camera schema migration unavailable: {e}")

    # Start camera service (wraps existing ScienceCameraDriver)
    try:
        from stcs_web.camera_service import start_camera_service
        start_camera_service()
        print("Camera service started (ScienceCameraDriver adapter)")
    except Exception as e:
        print(f"Warning: Could not start camera service: {e}")

    # Session secret validation at startup
    session_secret = os.environ.get("SESSION_SECRET")
    if session_secret is None:
        print("WARNING: SESSION_SECRET not set - using auto-generated value (acceptable for development only)")
        print("       Set SESSION_SECRET in the environment for production deployment")
    elif session_secret in ("dev-change-me-for-production", "your_session_secret_here", secrets.token_hex(32)):
        print(f"WARNING: SESSION_SECRET appears to be using a default/auto-generated value")
        print("       Set a unique, random SESSION_SECRET for production deployment")

    # Configuration validation at startup
    _validate_production_config()

    yield

    # Shutdown
    try:
        from stcs_web.camera_service import stop_camera_service
        stop_camera_service()
        print("Camera service stopped")
    except Exception:
        pass
    try:
        from stcs_web.command_service import stop_command_service
        stop_command_service()
        print("Command service stopped")
    except Exception:
        pass


def _validate_production_config():
    """Validate production configuration and warn about dangerous settings."""
    
    # Check STCS_COMMANDS_ENABLED - safe default is 0
    commands_enabled = os.environ.get("STCS_COMMANDS_ENABLED", "0")
    if commands_enabled == "1":
        print("WARNING: STCS_COMMANDS_ENABLED=1 — telescope commands will be accepted")
        print("         (safe default is STCS_COMMANDS_ENABLED=0)")
        print("         Physical commissioning must explicitly enable this setting")
    
    # Check for wildcard CORS origins
    cors_origins = os.environ.get("CORS_ORIGINS", "")
    if cors_origins == "*":
        print("WARNING: CORS_ORIGINS=* — wide open CORS, not recommended for production")
    
    # Check database configuration
    db_host = os.environ.get("DB_HOST", "localhost")
    db_name = os.environ.get("DB_NAME", "stcs_observatory")
    db_user = os.environ.get("DB_USER", "postgres")
    if not os.environ.get("DB_PASSWORD", ""):
        print(f"WARNING: DB_PASSWORD not set — database connectivity may fail")
        print(f"       Using DB_HOST={db_host}, DB_NAME={db_name}, DB_USER={db_user}")
    
    # Check for development-only settings that should not be in production
    telescope_mode = os.environ.get("TELESCOPE_MODE", "REAL").upper()
    if telescope_mode not in ("REAL", "SIMULATION"):
        print(f"WARNING: Unknown TELESCOPE_MODE='{telescope_mode}' — must be REAL or SIMULATION")

# ── FastAPI application ──────────────────────────────────────────────────
app = FastAPI(
    title="ARIES STCS Modernization",
    description="Modern web application for the 104 cm Sampurnanand Telescope",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Add security headers middleware
# These headers are added to all production responses
SECURE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

# CSP is configured compatible with existing inline scripts/styles
# Update these values if inline templates or script/style patterns change
CSP_DICT = {
    "default-src": "'self'",
    "script-src": "'self' 'unsafe-inline'",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data:",
    "connect-src": "'self'",
    "font-src": "'self'",
    "frame-ancestors": "'self'",
    "base-uri": "'self'",
    "form-action": "'self'",
}

# Only add HSTS when HTTPS is actually enabled via configuration
ENABLE_HSTS = os.environ.get("ENABLE_HSTS", "").lower() == "true"
if ENABLE_HSTS:
    # HSTS should only be active when secure cookies are also enabled
    # and HTTPS is being used. For now, require explicit opt-in.
    SECURE_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all production responses."""
    response = await call_next(request)
    for header, value in SECURE_HEADERS.items():
        response.headers[header] = value
    # Add CSP
    response.headers["Content-Security-Policy"] = (
        f"default-src {CSP_DICT['default-src']}; "
        f"script-src {CSP_DICT['script-src']}; "
        f"style-src {CSP_DICT['style-src']}; "
        f"img-src {CSP_DICT['img-src']}; "
        f"connect-src {CSP_DICT['connect-src']}; "
        f"font-src {CSP_DICT['font-src']}; "
        f"frame-ancestors {CSP_DICT['frame-ancestors']}; "
        f"base-uri {CSP_DICT['base-uri']}; "
        f"form-action {CSP_DICT['form-action']}"
    )
    return response

# Add session middleware.
# Secure cookie flag: True when HTTPS is enabled (deployment should set SESSION_SECURE_COOKIE=true)
SESSION_SECURE_COOKIE = os.environ.get("SESSION_SECURE_COOKIE", "").lower() == "true"
SESSION_HTTPONLY=True
SESSION_SAME_SITE="lax"  # "lax" for general use, "strict" for production-only workloads

app.add_middleware(
    SessionMiddleware,
    session_cookie="stcs_session",
    secret_key=os.environ.get("SESSION_SECRET", secrets.token_hex(32)),
    https_only=os.environ.get("SESSION_SECURE_COOKIE", "").lower() == "true",
    same_site=SESSION_SAME_SITE,
)

# Add CORS middleware
# Production CORS origins should be set via environment variable.
# Format: comma-separated list, e.g.: "https://example.com,https://sub.example.com"
# Development default restricts to localhost origins only.
CORS_ORIGINS_STR = os.environ.get("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS_STR.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Jinja2 templates
templates = Jinja2Templates(directory=os.path.join(str(STCS_WEB_DIR), "templates"))

# Template filters for display
def _display_state(value):
    """Operator-friendly words for internal telemetry states."""
    return {
        "LIVE": "Live",
        "STALE": "Stale",
        "NOT_CONNECTED": "Disconnected",
        "NOT_AVAILABLE": "Not available",
        "UNKNOWN": "Unknown",
    }.get(value, value)


def _age(value):
    """Format an epoch timestamp as a short relative age."""
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


templates.env.filters["disp"] = _display_state
templates.env.filters["age"] = _age

# Store templates in app state for routes to access
app.state.templates = templates

# Static assets (Phase 2 design system)
app.mount("/static", StaticFiles(directory=os.path.join(str(STCS_WEB_DIR), "static")), name="static")

# Include the API router.
# WHY no extra prefix here: routes.py already declares APIRouter(prefix="/api"),
# so include_router(router) yields /api/login. An extra prefix would create
# /api/api/login and break the login form action.
from stcs_web.routes import router
app.include_router(router, tags=["api"])

# Camera API routes (camera control, acquisition, file access)
from stcs_web.routes_camera import router as camera_router
app.include_router(camera_router, tags=["camera"])

# Phase 2 workspace pages + read-only APIs + safe command gate
from stcs_web.pages import router as pages_router
app.include_router(pages_router)


# ── Template rendering ───────────────────────────────────────────────────
def template(name: str, request: Request, **context) -> HTMLResponse:
    """Render a Jinja2 template (Starlette>=1.x: request first)."""
    return templates.TemplateResponse(request, name, context)


# ── Health check ─────────────────────────────────────────────────────────
@app.get("/health", include_in_schema=False)
async def health_check_endpoint():
    """Application health check.
    
    Returns overall application status. Does NOT indicate telescope readiness.
    For telescope hardware health, use /api/telemetry/snapshot.
    For database health, check PostgreSQL connectivity.
    """
    from stcs_web import database as _db
    from stcs_web import obs_store as _obs
    
    # Application-level check
    app_ok = True
    
    # Database check
    db_ok = False
    try:
        conn = _db.get_db_connection()
        conn.close()
        db_ok = True
    except Exception:
        pass
    
    # Telescope telemetry check (via Alpaca/WS - already implemented in obs_store)
    telemetry_ok = _obs.db_available() if hasattr(_obs, 'db_available') else False
    
    # Camera service check
    cam_ok = False
    try:
        from stcs_web.camera_service import get_camera_service
        svc = get_camera_service()
        if svc:
            cam_ok = svc._adapter is not None
    except Exception:
        pass
    
    status = "ok" if app_ok else "degraded"
    details = {
        "status": status,
        "service": "STCS Web Application",
        "phase": "2",
        "database": "available" if db_ok else "unavailable",
        "telemetry": "available" if telemetry_ok else "unavailable",
        "camera": "available" if cam_ok else "unavailable",
    }
    return details


@app.get("/api/health", include_in_schema=False)
async def api_health_check_endpoint():
    """API health check endpoint.
    
    Returns basic status for infrastructure monitoring.
    Does NOT report telescope hardware availability.
    """
    return {
        "status": "ok",
        "service": "STCS Web Application",
        "version": "1.0.0",
    }


# ── Legacy non-/api routes → canonical /api routes ───────────────────────
# WHY redirects instead of duplicate handlers: Phase 1 created two parallel
# auth paths (/login in main.py and /api/login in routes.py). Parallel paths
# risk CSRF/validation drift, so the legacy paths now redirect to the single
# canonical CSRF-protected implementation in routes.py.
@app.get("/login", include_in_schema=False)
async def login_get(request: Request):
    return RedirectResponse(url="/api/login", status_code=302)


@app.post("/login", include_in_schema=False)
async def login_post(request: Request, response: Response):
    return RedirectResponse(url="/api/login", status_code=302)


@app.post("/logout", include_in_schema=False)
async def logout(request: Request, response: Response):
    return RedirectResponse(url="/api/login", status_code=302)


@app.get("/auth/check", include_in_schema=False)
async def auth_check(request: Request):
    return RedirectResponse(url="/api/auth/check", status_code=302)


@app.get("/dashboard", include_in_schema=False)
async def dashboard(request: Request):
    return RedirectResponse(url="/app/control", status_code=302)


@app.get("/", include_in_schema=False)
async def index(request: Request):
    """Root entry point → observatory shell (or login when logged out)."""
    user = request.session.get("stcs_user")
    if user is None:
        return RedirectResponse(url="/api/login", status_code=302)
    return RedirectResponse(url="/app/control", status_code=302)


# ── Main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    reload = os.environ.get("WEB_RELOAD", "0") == "1"

    print(f"Starting STCS Web Application...")
    print(f"  Environment: {os.environ.get('TELESCOPE_MODE', 'REAL')} telescope mode")
    print(f"  Listening on: http://{host}:{port}")
    print(f"  API docs: http://{host}:{port}/api/docs")
    print(f"  Login: http://{host}:{port}/api/login")
    print()
    print("Phase 2: Real web observatory system")
    print("  - CONTROL / OBSERVATIONS / CAMERA / SYSTEM / ADMIN workspaces")
    print("  - Real read-only telemetry (Alpaca 11111, UDP weather 12344, STCS config)")
    print("  - Phase 1 auth preserved: bcrypt, sessions, CSRF, role separation")
    print("  - Commands validated only (STCS_COMMANDS_ENABLED=0); no motion executed")
    print()
    print("NOTE: No physical telescope motion during development/testing.")
    print("      The existing STCS V1 desktop application is untouched.")

    uvicorn.run(app, host=host, port=port, reload=reload)