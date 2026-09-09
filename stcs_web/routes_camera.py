"""
Camera API routes — endpoints for camera control, acquisition, and file access.

All endpoints require authentication. CSRF validation is enforced on mutating
endpoints. Privacy is enforced server-side: scientists see only their own
observations and files.

Endpoints:
  GET  /api/camera/status           — camera status JSON
  POST /api/camera/connect          — connect to camera
  POST /api/camera/disconnect       — disconnect from camera
  POST /api/camera/configure        — configure camera settings
  POST /api/camera/acquire          — start observation acquisition
  GET  /api/camera/acquisition/status — current acquisition status
  POST /api/camera/abort            — abort current acquisition
  GET  /api/camera/observations     — list user's camera observations
  GET  /api/camera/observation/{id} — observation detail with files
  GET  /api/camera/file/{id}        — download observation file (authorized)
"""

import hashlib
import json
import logging
import os
from typing import Optional

import hmac

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from . import auth
from . import obs_store

logger = logging.getLogger("CameraRoutes")

router = APIRouter(prefix="/api/camera", tags=["camera"])


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_user_or_401(request: Request):
    """Get current user or raise 401."""
    user = auth.get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _get_camera_service():
    """Get the camera service singleton."""
    from .camera_service import get_camera_service
    svc = get_camera_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Camera service not available")
    return svc


def _audit(username: str, action: str, detail: str = ""):
    """Best-effort audit log."""
    try:
        obs_store.record_audit(username, action, detail[:2000])
    except Exception:
        pass


def _csrf_validate_json(body: dict, request: Request) -> bool:
    """Validate CSRF token from a JSON request body."""
    try:
        form_token = (body.get("_stcs_csrf_token") or "").strip()
    except Exception:
        return False
    session_token = request.session.get("_stcs_csrf_token") or ""
    if not form_token or not session_token:
        return False
    return hmac.compare_digest(form_token, session_token)


# ── Camera status ──────────────────────────────────────────────────────────

@router.get("/status")
async def camera_status(request: Request):
    """Return current camera status. No side effects."""
    user = _get_user_or_401(request)
    svc = _get_camera_service()
    return svc.get_camera_status()


# ── Connect / Disconnect ──────────────────────────────────────────────────

@router.post("/connect")
async def camera_connect(request: Request):
    """Connect to the camera via LightField."""
    user = _get_user_or_401(request)
    # Validate CSRF token from JSON body
    body = await request.json()
    if not _csrf_validate_json(body, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    svc = _get_camera_service()
    result = svc.connect_camera()
    _audit(user["username"], "camera_connect",
           f"success={result.get('success')} mock={result.get('mock_mode')}")
    return result


@router.post("/disconnect")
async def camera_disconnect(request: Request):
    """Disconnect from the camera."""
    user = _get_user_or_401(request)
    # Validate CSRF token from JSON body
    body = await request.json()
    if not _csrf_validate_json(body, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    svc = _get_camera_service()
    result = svc.disconnect_camera()
    _audit(user["username"], "camera_disconnect",
           f"success={result.get('success')}")
    return result


# ── Configure ──────────────────────────────────────────────────────────────

@router.post("/configure")
async def camera_configure(request: Request):
    """Configure camera settings (exposure, gain, binning, etc.).
    
    Body: JSON with camera settings keys.
    """
    user = _get_user_or_401(request)
    # Validate CSRF token from JSON body
    body = await request.json()
    if not _csrf_validate_json(body, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    
    result = svc.configure_camera(body)
    _audit(user["username"], "camera_configure",
           f"success={result.get('success')} settings={list(body.keys())}")
    return result


# ── Acquire ────────────────────────────────────────────────────────────────

@router.post("/acquire")
async def camera_acquire(request: Request):
    """Start observation acquisition.
    
    Body: JSON with:
      target: str — target name (required)
      notes: str — observation notes (optional)
      exposure: float — exposure time in seconds (optional, overrides configure)
      gain: str — gain setting (optional)
      shutter: str — shutter mode (optional)
      binning: [x, y] — binning pair (optional)
      adc_speed: str — ADC speed (optional)
      readout_mode: str — readout mode (optional)
      frames_to_save: int — number of frames (optional)
      And any other camera settings supported by the driver.
    
    This is a BLOCKING endpoint. It waits for the full acquisition cycle
    to complete (exposure + readout + save). Timeout: ~180s.
    """
    user = _get_user_or_401(request)
    # Validate CSRF token from JSON body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not _csrf_validate_json(body, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    target = body.pop("target", "untitled")
    notes = body.pop("notes", "")
    settings = body  # remaining keys are camera settings

    result = svc.start_acquisition(
        target=target,
        settings=settings,
        username=user["username"],
        notes=notes,
    )
    return result


# ── Acquisition status ────────────────────────────────────────────────────

@router.get("/acquisition/status")
async def acquisition_status(request: Request):
    """Return current acquisition status (non-blocking)."""
    user = _get_user_or_401(request)
    svc = _get_camera_service()
    return svc.get_acquisition_status()


# ── Abort ──────────────────────────────────────────────────────────────────

@router.post("/abort")
async def camera_abort(request: Request):
    """Abort the current acquisition.

    Only the user who started the acquisition may abort it.
    """
    user = _get_user_or_401(request)
    # Validate CSRF token from JSON body
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not _csrf_validate_json(body, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    result = svc.abort_acquisition(user["username"])
    _audit(user["username"], "camera_abort",
           f"success={result.get('success')}")
    return result


# ── Observations list ─────────────────────────────────────────────────────

@router.get("/observations")
async def camera_observations(
    request: Request,
    q: str = Query("", description="Search target/notes"),
    status: str = Query("", description="Filter by status"),
    date_from: str = Query("", description="Start date ISO"),
    date_to: str = Query("", description="End date ISO"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List observations visible to the current user."""
    user = _get_user_or_401(request)
    result = obs_store.list_observations(
        username=user["username"],
        role=user.get("role", "scientist"),
        q=q, status=status,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    return result


# ── Observation detail ────────────────────────────────────────────────────

@router.get("/observation/{obs_id}")
async def camera_observation_detail(request: Request, obs_id: int):
    """Get observation detail with telescope state and files.

    Privacy: scientists see only their own observations.
    """
    user = _get_user_or_401(request)
    obs = obs_store.get_observation_with_files(
        obs_id, user["username"], user.get("role", "scientist")
    )
    if obs is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return obs


# ── File download ──────────────────────────────────────────────────────────

@router.get("/file/{file_id}")
async def camera_file_download(request: Request, file_id: int):
    """Download an observation file.

    Privacy: scientists can only download their own files.
    The original .spe file is served as-is — no conversion.
    """
    user = _get_user_or_401(request)
    file_info = obs_store.get_file_for_download(
        file_id, user["username"], user.get("role", "scientist")
    )
    if file_info is None:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = file_info["file_path"]
    filename = file_info["filename"]

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    # Prevent path traversal (defense in depth)
    real_path = os.path.realpath(file_path)
    # Verify the resolved path doesn't contain .. components and
    # the database-stored path resolves cleanly
    if ".." in file_path:
        raise HTTPException(status_code=403, detail="Invalid file path")

    _audit(user["username"], "file_download",
           f"file_id={file_id} filename={filename}")

    return FileResponse(
        path=real_path,
        filename=filename,
        media_type="application/octet-stream",
    )


# ── File metadata (no download) ──────────────────────────────────────────

@router.get("/files")
async def camera_files_list(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all observation files visible to the current user."""
    user = _get_user_or_401(request)
    result = obs_store.list_observation_files(
        username=user["username"],
        role=user.get("role", "scientist"),
        limit=limit,
        offset=offset,
    )
    return result
