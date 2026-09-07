"""
Phase 2 workspace pages + read-only JSON APIs + safe command gate.

WHY this module exists:
  Phase 1 proved authentication. Phase 2 adds the observatory workspaces
  (CONTROL / CHECKUP / HISTORY / CAMERA / SYSTEM / ADMIN) on top of the
  same session auth, bcrypt passwords, and CSRF protection.

SAFETY MODEL (read carefully):
  - All *telemetry* endpoints here are READ-ONLY (Alpaca GETs, UDP listen,
    config files). They never move hardware.
  - All *command* intents go through POST /api/command/validate, which
    mirrors the existing STCS validation sets (VALID_COMMANDS / speeds /
    directions from telemetry_server.py) and then REFUSES execution unless
    STCS_COMMANDS_ENABLED=1 AND the caller holds the control lock. During
    development/testing commands are validated only — nothing moves.
  - The browser never touches Arduino/serial/relay code paths. A future
    reviewed adapter may bridge the validated intent to the existing
    MotionState/SlewEngine path; that bridge does not exist yet and must
    pass RULE 20 review before any physical test.
"""

import csv
import io
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from . import auth
from . import observatory as obs_svc
from . import obs_store
from .routes import _csrf_token, _csrf_validate_form, template_response

router = APIRouter(tags=["observatory"])

COMMANDS_ENABLED = os.environ.get("STCS_COMMANDS_ENABLED", "0") == "1"

# Mirror of the existing STCS validation sets (telemetry_server.py:36-52).
VALID_COMMANDS = {"manual_move", "stop", "tracking_on", "tracking_off",
                  "dome_cw", "dome_ccw", "dome_off", "heartbeat",
                  "slewtocoordinatesasync", "park", "emergency_stop",
                  "synccalibration", "clear_offsets"}
VALID_SPEEDS = {"COARSE", "FINE_1", "FINE_2"}
VALID_DIRECTIONS = {"RA": {"EAST", "WEST", "NONE"},
                    "DEC": {"NORTH", "SOUTH", "NONE"}}


def _require_user(request: Request):
    user = auth.get_current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Authentication required")
    return user


def _page_ctx(request: Request, user, snap, extra=None):
    safety = (snap.get("safety") or {}).get("overall", "UNKNOWN")
    alert_cls = {"SAFE": "safe", "WARNING": "warn", "CRITICAL": "crit"}.get(safety, "unk")
    alert_text = {
        "safe": "ALL SYSTEMS NOMINAL",
        "warn": "ADVISORY — CHECK SAFETY PANEL",
        "crit": "SAFETY CONDITION — REVIEW BEFORE OPERATING",
    }.get(alert_cls, "TELEMETRY UNAVAILABLE — STATE UNKNOWN")
    alp = (snap.get("alpaca") or {}).get("status", "UNKNOWN")
    led = "ok" if alp == "LIVE" else ("warn" if alp == "STALE" else "bad")
    ctx = {
        "request": request,
        "username": user["username"],
        "role": user["role"],
        "csrf_token": _csrf_token(request),
        "snap": snap,
        "db_ok": obs_store.db_available(),
        "mode": snap.get("mode", "REAL"),
        "system_state": _system_state(snap),
        "alert_cls": alert_cls,
        "alert_text": alert_text,
        "led": led,
        "commands_enabled": "YES" if COMMANDS_ENABLED else "NO",
    }
    if extra:
        ctx.update(extra)
    return ctx


def _system_state(snap):
    if snap.get("mode") == "SIMULATION":
        return "◆ SIMULATION"
    st = (snap.get("alpaca") or {}).get("status", "UNKNOWN")
    if st == "LIVE":
        return "● READY"
    if st == "STALE":
        return "⚠ STALE"
    return "○ DISCONNECTED"


def _hms(hours):
    if hours is None:
        return "—"
    hours = hours % 24.0
    h = int(hours)
    m = int((hours - h) * 60.0)
    s = (hours - h - m / 60.0) * 3600.0
    return f"{h:02d}:{m:02d}:{s:04.1f}"


# ── Workspace pages ─────────────────────────────────────────────────────
@router.get("/app/control", include_in_schema=False)
async def page_control(request: Request):
    user = auth.get_current_user(request)
    if user is None:
        return RedirectResponse(url="/api/login", status_code=302)
    snap = obs_svc.observatory_snapshot()
    v = snap["alpaca"]["values"]
    ra = v.get("rightascension")
    lst = snap["lst"]
    # HRA = LST - RA (same relation as LegacyDecoder HRA→RA via LST)
    hra = ((lst - ra) % 24.0) if (lst is not None and ra is not None) else None
    import time as _t
    alp_age = _t.time() - (snap["alpaca"].get("updated_at") or 0.0)
    wvals = snap["weather"].get("values") or {}
    wx_age = (f"{snap['weather'].get('age_s', 0.0):.1f}s"
              if wvals else "—")
    ctx = _page_ctx(request, user, snap, {
        "page_title": "Control", "active": "control",
        "ra_hms": obs_svc.fmt_ra_hms(ra),
        "hra_hms": obs_svc.fmt_ra_hms(hra),
        "dec_dms": obs_svc.fmt_dec_dms(v.get("declination")),
        "az": obs_svc.fmt_deg(v.get("azimuth")),
        "alt": obs_svc.fmt_deg(v.get("altitude")),
        "lst_hms": _hms(lst),
        "jd": f"{snap['jd']:.5f}",
        "dome_az": "—",
        "dome_state": ("MOVING" if v.get("slewing")
                       else ("—" if v.get("slewing") is False else "Unknown")),
        "dome_sync": "Unknown",
        "tracking": ("ON" if v.get("tracking") is True
                     else ("OFF" if v.get("tracking") is False else "UNKNOWN")),
        "sidereal": ("ON" if v.get("tracking") is True
                     else ("OFF" if v.get("tracking") is False else "Unknown")),
        "slewing": v.get("slewing"),
        "atpark": v.get("atpark"), "athome": v.get("athome"),
        "motion_state": ("SLEWING" if v.get("slewing") is True
                         else ("IDLE" if v.get("slewing") is False else "UNKNOWN")),
        "alp_age": f"{alp_age:.1f}s",
        "wx_age": wx_age,
        "w_temp": wvals.get("temp_c", "—"),
        "w_hum": wvals.get("humidity_pct", "—"),
        "w_dew": wvals.get("dew_point_c", "—"),
        "dec_home": ((snap.get("config") or {}).get("state") or {}).get("dec_home_deg", "—"),
        "ra_off": ((snap.get("config") or {}).get("state") or {}).get("minor_hra_adj", "—"),
        "dec_off": ((snap.get("config") or {}).get("state") or {}).get("minor_dec_adj", "—"),
        "dome_off": ((snap.get("config") or {}).get("state") or {}).get("dome_offset", "—"),
        "site_lat": v.get("sitelatitude") or "29.36",
        "site_lon": v.get("sitelongitude") or "79.45",
        "cmd_result": request.query_params.get("cmd", ""),
    })
    return template_response("control.html", **ctx)


@router.get("/app/checkup", include_in_schema=False)
async def page_checkup_retired(request: Request):
    """CHECKUP was merged into CONTROL — redirect, never a dead link."""
    return RedirectResponse(url="/app/control", status_code=302)


@router.get("/app/history", include_in_schema=False)
async def page_history_retired(request: Request):
    """Old history URL → canonical observations archive."""
    return RedirectResponse(url="/app/observations", status_code=302)


@router.get("/app/syscam", include_in_schema=False)
async def page_syscam_retired(request: Request):
    """Retired merged page → SYSTEM (camera lives at /app/camera)."""
    return RedirectResponse(url="/app/system", status_code=302)


@router.get("/app/observations", include_in_schema=False)
async def page_history(request: Request):
    user = auth.get_current_user(request)
    if user is None:
        return RedirectResponse(url="/api/login", status_code=302)
    snap = obs_svc.observatory_snapshot()
    qp = request.query_params
    page = max(1, int(qp.get("page", "1") or 1))
    limit = 15
    filt = {"q": qp.get("q", ""), "status": qp.get("status", ""),
            "date_from": qp.get("from", ""), "date_to": qp.get("to", "")}
    owner_filter = qp.get("owner", "")
    eff_user, eff_role = user["username"], user["role"]
    if user["role"] == "admin" and owner_filter:
        eff_user, eff_role = owner_filter, "scientist"
    try:
        res = obs_store.list_observations(eff_user, eff_role, limit=limit,
                                          offset=(page - 1) * limit, **filt)
        try:
            mine = obs_store.list_observations(user["username"], user["role"],
                                               limit=1000)
            durations = [m.get("duration_s") or 0 for m in mine["items"]]
            summary = {"total": mine["total"],
                       "hours": round(sum(durations) / 3600.0, 2),
                       "targets": len({m.get("target") for m in mine["items"]}),
                       "latest": mine["items"][0]["start"] if mine["items"] else "—"}
        except Exception:
            summary = {"total": res["total"], "hours": "—", "targets": "—", "latest": "—"}
    except Exception:
        res = {"total": 0, "items": []}
        summary = {"total": 0, "hours": "—", "targets": "—", "latest": "—"}
    detail = None
    if qp.get("obs"):
        try:
            detail = obs_store.get_observation(int(qp["obs"]), user["username"], user["role"])
        except Exception:
            detail = None
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    _now = _dt.now(_tz.utc).date()
    ctx = _page_ctx(request, user, snap, {
        "page_title": "Observations", "active": "observations",
        "items": res["items"], "total": res["total"], "page": page,
        "summary": summary, "q": filt["q"], "status_f": filt["status"],
        "date_from": filt["date_from"], "date_to": filt["date_to"],
        "owner_filter": owner_filter, "detail": detail,
        "today": _now.isoformat(),
        "week_ago": (_now - _td(days=7)).isoformat(),
        "month_ago": (_now - _td(days=30)).isoformat(),
    })
    return template_response("observations.html", **ctx)


@router.get("/app/camera", include_in_schema=False)
async def page_camera(request: Request):
    """Dedicated camera workspace: status, acquisition, images."""
    user = auth.get_current_user(request)
    if user is None:
        return RedirectResponse(url="/api/login", status_code=302)
    snap = obs_svc.observatory_snapshot()
    return template_response("camera.html", **_page_ctx(
        request, user, snap, {"page_title": "Camera", "active": "camera"}))


@router.get("/app/system", include_in_schema=False)
async def page_system(request: Request):
    """Engineering diagnostics: health, connections, logs, configuration."""
    user = auth.get_current_user(request)
    if user is None:
        return RedirectResponse(url="/api/login", status_code=302)
    snap = obs_svc.observatory_snapshot()
    cfg = snap.get("config") or {}
    limits = (cfg.get("limits") or {}).get("motion", {})
    audit = _recent_audit()
    db_ok = obs_store.db_available()
    # WHY rewrite two rows: the snapshot builder cannot see PostgreSQL, so it
    # reports Database/WebApp as UNKNOWN. Here the real states are known.
    subs = []
    for name, st, ts in snap.get("subsystems", []):
        if name == "Database":
            subs.append((name, "LIVE" if db_ok else "NOT_CONNECTED", ts))
        elif name == "Web Application":
            import time as _t3
            subs.append((name, "LIVE", _t3.time()))
        else:
            subs.append((name, st, ts))
    snap = dict(snap, subsystems=subs)
    ctx = _page_ctx(request, user, snap, {
        "page_title": "System", "active": "system", "audit": audit,
        "alt_floor": limits.get("min_altitude_deg", "—"),
        "alt_max": limits.get("max_altitude_deg", "—"),
        "site_lat": "29.36", "site_lon": "79.45",
    })
    return template_response("system.html", **ctx)


@router.get("/app/admin", include_in_schema=False)
async def page_admin(request: Request):
    user = auth.get_current_user(request)
    if user is None or user["role"] != "admin":
        return RedirectResponse(url="/api/login", status_code=302)
    snap = obs_svc.observatory_snapshot()
    users, items = [], []
    try:
        from .database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT username, role, is_active FROM users ORDER BY username")
                users = [{"username": r[0], "role": r[1], "is_active": r[2]}
                         for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        users = [{"username": user["username"], "role": user["role"], "is_active": True}]
    try:
        items = obs_store.list_observations(user["username"], "admin", limit=50)["items"]
    except Exception:
        items = []
    return template_response("admin.html", **_page_ctx(
        request, user, snap, {"page_title": "Admin", "active": "admin",
                              "users": users, "items": items,
                              "audit": _recent_audit()}))


def _recent_audit(limit=50):
    try:
        from .database import get_db_connection
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT actor_username, action, detail, created_at "
                            "FROM audit_events ORDER BY id DESC LIMIT %s", (limit,))
                return cur.fetchall()
        finally:
            conn.close()
    except Exception:
        return []


# ── Read-only JSON APIs ─────────────────────────────────────────────────
@router.get("/api/telemetry/snapshot", include_in_schema=False)
async def api_snapshot(request: Request):
    _require_user(request)
    snap = obs_svc.observatory_snapshot()
    v = snap["alpaca"]["values"]
    return {"mode": snap["mode"], "alpaca_status": snap["alpaca"]["status"],
            "ra_hours": v.get("rightascension"), "dec_deg": v.get("declination"),
            "lst_hours": snap["lst"], "lst_source": snap["lst_source"],
            "alt_deg": v.get("altitude"), "az_deg": v.get("azimuth"),
            "tracking": v.get("tracking"), "slewing": v.get("slewing"),
            "atpark": v.get("atpark"), "athome": v.get("athome"),
            "weather": snap["weather"], "safety": snap["safety"],
            "subsystems": snap["subsystems"],
            "generated_at": snap["generated_at"]}


@router.get("/api/history/list", include_in_schema=False)
async def api_history_list(request: Request):
    user = _require_user(request)
    qp = request.query_params
    try:
        return obs_store.list_observations(
            user["username"], user["role"], q=qp.get("q", ""),
            status=qp.get("status", ""), date_from=qp.get("from", ""),
            date_to=qp.get("to", ""),
            limit=min(100, int(qp.get("limit", "25") or 25)),
            offset=int(qp.get("offset", "0") or 0))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


@router.get("/api/history/export", include_in_schema=False)
async def api_history_export(request: Request, fmt: str = "csv"):
    """Export ONLY records the caller is authorized to see."""
    user = _require_user(request)
    try:
        res = obs_store.list_observations(user["username"], user["role"], limit=5000)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")
    obs_store.record_audit(user["username"], "observation_export",
                           f"fmt={fmt} count={res['total']}")
    if fmt == "json":
        return JSONResponse(res)
    cols = ["id", "owner", "target", "ra_deg", "dec_deg", "start",
            "end", "duration_s", "status"]
    rows = [[o["id"], o["owner"], o["target"], o["ra_deg"], o["dec_deg"],
             o["start"], o["end"], o["duration_s"], o["status"]]
            for o in res["items"]]
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Observations"
        ws.append(cols)
        for r in rows:
            ws.append(r)
        for col in ws.columns:
            col[0].font = col[0].font.copy(bold=True)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]),
                                 media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition":
                                          "attachment; filename=observations.xlsx"})
    if fmt == "pdf":
        from fpdf import FPDF
        pdf = FPDF(orientation="L", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "ARIES 104 cm — Observation Export", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6, f"Exported by {user['username']} ({user['role']}) — {len(rows)} record(s), privacy-filtered",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        widths = [12, 30, 60, 22, 22, 38, 38, 22, 28]
        pdf.set_font("Helvetica", "B", 8)
        for i, c in enumerate(cols):
            pdf.cell(widths[i], 7, c, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        for r in rows:
            for i, v in enumerate(r):
                pdf.cell(widths[i], 6, str(v if v is not None else "—"), border=1)
            pdf.ln()
        out = bytes(pdf.output())
        return StreamingResponse(iter([out]), media_type="application/pdf",
                                 headers={"Content-Disposition":
                                          "attachment; filename=observations.pdf"})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=observations.csv"})


# ── Safe command gate (validate first, execute only when enabled) ───────
def _validate_command(cmd, fields):
    """Mirror the existing STCS validation sets. Returns (ok, message)."""
    if cmd not in VALID_COMMANDS:
        return False, f"Unknown command '{cmd}'"
    if cmd == "manual_move":
        axis = (fields.get("axis") or "").upper()
        direction = (fields.get("direction") or "").upper()
        speed = (fields.get("speed") or "").upper()
        if axis not in VALID_DIRECTIONS:
            return False, "axis must be RA or DEC"
        if direction not in VALID_DIRECTIONS[axis]:
            return False, f"direction '{direction}' invalid for {axis}"
        if speed not in VALID_SPEEDS:
            return False, f"speed must be one of {sorted(VALID_SPEEDS)}"
        return True, "manual_move valid"
    if cmd == "slewtocoordinatesasync":
        try:
            ra = float(fields.get("ra_deg", ""))
            dec = float(fields.get("dec_deg", ""))
        except (TypeError, ValueError):
            return False, "ra_deg/dec_deg must be numbers"
        if not (-90.0 <= dec <= 90.0):
            return False, "dec out of range"
        return True, f"slew target RA={ra} DEC={dec} valid"
    return True, f"{cmd} valid"


@router.post("/api/command/validate", include_in_schema=False)
async def api_command_validate(request: Request):
    """Validate a command intent. Executes NOTHING unless explicitly enabled.

    Even when STCS_COMMANDS_ENABLED=1, execution requires the caller to hold
    the control lock AND a reviewed hardware bridge (not present in Phase 2),
    so this endpoint returns executed:false with the reason. Physical motion
    stays reserved for controlled validation (RULE 20).
    """
    user = _require_user(request)
    form = await request.form()
    if not _csrf_validate_form(form, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    fields = dict(form)
    cmd = (fields.get("command") or "").strip()
    ok, message = _validate_command(cmd, fields)
    if not ok:
        obs_store.record_audit(user["username"], "command_rejected", f"{cmd}: {message}")
        raise HTTPException(status_code=400, detail=message)
    lock = obs_svc.control_lock_status()

    def _respond(payload):
        """Browsers (form posts) go back to CONTROL; API clients keep JSON."""
        accept = request.headers.get("accept", "")
        if "text/html" in accept and payload.get("redirect"):
            return RedirectResponse(url=payload["redirect"], status_code=302)
        return payload

    if not COMMANDS_ENABLED:
        obs_store.record_audit(user["username"], "command_validated", f"{cmd}: {message} (not executed; commands disabled)")
        return _respond({"ok": True, "executed": False, "command": cmd, "message": message,
                "reason": "STCS_COMMANDS_ENABLED=0 — validation only, no motion",
                "redirect": f"/app/control?cmd={cmd}+validated+(no+motion)"})
    if lock["owner"] != user["username"]:
        return _respond({"ok": False, "executed": False, "command": cmd,
                "reason": f"Control lock held by {lock['owner'] or 'nobody'} — acquire it first",
                "redirect": "/app/control?cmd=lock+required"})
    obs_store.record_audit(user["username"], "command_validated", f"{cmd}: {message} (bridge pending review)")
    return _respond({"ok": True, "executed": False, "command": cmd, "message": message,
            "reason": "Hardware bridge pending RULE-20 review — no motion executed",
            "redirect": "/app/control?cmd=bridge+pending+review"})


@router.post("/api/command/lock", include_in_schema=False)
async def api_lock(request: Request):
    user = _require_user(request)
    form = await request.form()
    if not _csrf_validate_form(form, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    res = obs_svc.acquire_control_lock(user["username"])
    obs_store.record_audit(user["username"], "control_lock",
                           f"acquire ok={res['ok']} owner={res.get('owner')}")
    return RedirectResponse(url="/app/control", status_code=302)


@router.post("/api/command/unlock", include_in_schema=False)
async def api_unlock(request: Request):
    user = _require_user(request)
    form = await request.form()
    if not _csrf_validate_form(form, request):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    obs_svc.release_control_lock(user["username"], user["role"])
    obs_store.record_audit(user["username"], "control_lock", "release")
    return RedirectResponse(url="/app/control", status_code=302)
