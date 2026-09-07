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
import psycopg2

# Path layout: STCS_WEB_DIR = .../GUI/stcs_web, PROJECT_ROOT = .../GUI.
# WHY two names: templates/static/fallback files live under stcs_web/,
# while imports need the project root on sys.path.
STCS_WEB_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = STCS_WEB_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── Password hashing helper ──────────────────────────────────────────────
def hash_password(password: str) -> str:
    """Hash a password using bcrypt.
    
    Returns a bcrypt hash string that includes the cost factor, salt, and hash.
    Never store plaintext passwords.
    """
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


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

    # Create default development users directly (without database dependency)
    import os
    admin_username = os.environ.get("ADMIN_USERNAME", "Admin")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Admin@123")
    scientist_username = os.environ.get("SCIENTIST_USERNAME", "Scientist1")
    scientist_password = os.environ.get("SCIENTIST_PASSWORD", "Pass@123")

    # Use file-based fallback for development credentials
    # Passwords are hashed with bcrypt; verification uses the same algorithm
    hashed_admin = hash_password(admin_password)
    hashed_scientist = hash_password(scientist_password)

    # Store fallback credentials in a simple file for session verification
    fallback_file = os.path.join(str(STCS_WEB_DIR), "fallback_creds.txt")
    try:
        # WHY exact configured names: get_user_by_username() matches the
        # username string exactly, so the file must store "Admin" (not
        # "admin") and "Scientist1" (not "scientist1").
        with open(fallback_file, "w") as f:
            f.write(f"{admin_username}:{hashed_admin}:admin\n")
            f.write(f"{scientist_username}:{hashed_scientist}:scientist\n")
        print(f"Fallback credentials stored at {fallback_file}")
    except Exception:
        pass
    
    yield
    
    # Shutdown (if needed)
    pass


# ── FastAPI application ──────────────────────────────────────────────────
app = FastAPI(
    title="ARIES STCS Modernization",
    description="Modern web application for the 104 cm Sampurnanand Telescope",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Add session middleware.
# NOTE: installed Starlette 1.6.0 names the cookie parameter
# `session_cookie` (older docs show `session_cookie_name`). Verified via
# inspect.signature(SessionMiddleware.__init__) in this environment.
app.add_middleware(
    SessionMiddleware,
    session_cookie="stcs_session",
    secret_key=os.environ.get("SESSION_SECRET", secrets.token_hex(32)),
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Jinja2 templates
templates = Jinja2Templates(directory=os.path.join(str(STCS_WEB_DIR), "templates"))

# Static assets (Phase 2 design system)
app.mount("/static", StaticFiles(directory=os.path.join(str(STCS_WEB_DIR), "static")), name="static")

# Include the API router.
# WHY no extra prefix here: routes.py already declares APIRouter(prefix="/api"),
# so include_router(router) yields /api/login. An extra prefix would create
# /api/api/login and break the login form action.
from stcs_web.routes import router
app.include_router(router, tags=["api"])

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
    return {"status": "ok", "service": "STCS Web Application", "phase": "2"}

@app.get("/api/health", include_in_schema=False)
async def api_health_check_endpoint():
    return {"status": "ok", "service": "STCS Web Application", "phase": "2"}


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