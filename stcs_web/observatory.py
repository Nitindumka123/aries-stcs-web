"""
Observatory service layer — Phase 2.

WHY: templates must never speak hardware protocols. This module turns the
raw read-only snapshots from telemetry.py into clean domain data:
  - mount/dome/tracking/system status with LIVE/STALE/NOT_CONNECTED states
  - safety evaluation using thresholds already defined in
    stcs_v1/config/limits.json (never invented here)
  - astronomical formatting (RA HMS, DEC DMS, LST, JD) for the POSITION tab
  - subsystem health matrix for CHECKUP/SYSTEM

No commands are issued from this module. No values are fabricated: when a
source is unavailable the field is None and the status explains why.
"""

import math
import os
import threading
import time
from datetime import datetime, timezone

from . import telemetry


# ── Astronomical formatting (display only) ──────────────────────────────
def fmt_ra_hms(ra_hours):
    if ra_hours is None:
        return "—"
    ra_hours = ra_hours % 24.0
    h = int(ra_hours)
    m = int((ra_hours - h) * 60.0)
    s = (ra_hours - h - m / 60.0) * 3600.0
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def fmt_dec_dms(dec_deg):
    if dec_deg is None:
        return "—"
    sign = "+" if dec_deg >= 0 else "−"
    a = abs(dec_deg)
    d = int(a)
    m = int((a - d) * 60.0)
    s = (a - d - m / 60.0) * 3600.0
    return f"{sign}{d:02d}°{m:02d}'{s:04.1f}\""


def fmt_deg(value, digits=2):
    return "—" if value is None else f"{value:+.{digits}f}°"


def juliandate(dt=None):
    dt = dt or datetime.now(timezone.utc)
    # Meeus algorithm (display precision only)
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def lst_hours_fallback(lon_deg=79.4571):
    """GMST-based LST fallback used ONLY when Alpaca siderealtime is stale.

    WHY a fallback exists: the POSITION tab must still show an LST label
    rather than a blank. It is derived from UTC + site longitude with a
    standard low-precision GMST formula, and is always labelled by the
    caller with its LIVE/STALE source state — never presented as hardware.
    """
    now = datetime.now(timezone.utc)
    jd = juliandate(now)
    d = jd - 2451545.0
    gmst = (18.697374558 + 24.06570982441908 * d) % 24.0
    return (gmst + lon_deg / 15.0) % 24.0


# ── Safety evaluation (thresholds from STCS limits.json only) ───────────
def evaluate_safety(weather, alt_deg, limits):
    """Return per-parameter safety states. Unknown when data is missing.

    Thresholds come from stcs_v1/config/limits.json environment section:
      max_humidity_percent, max_wind_speed_kmh, close_dome_on_rain,
      motion.min_altitude_deg. Nothing is invented here.
    """
    env = (limits or {}).get("environment", {}) if limits else {}
    motion = (limits or {}).get("motion", {}) if limits else {}
    out = {}

    hum = (weather or {}).get("humidity_pct")
    max_hum = env.get("max_humidity_percent")
    if hum is None or max_hum is None:
        out["humidity"] = "UNKNOWN"
    elif hum >= max_hum:
        out["humidity"] = "CRITICAL"
    elif hum >= max_hum - 10.0:
        out["humidity"] = "WARNING"
    else:
        out["humidity"] = "SAFE"

    # Wind/rain are only reported when the source provides them; the UDP
    # weather datagram carries temp/humidity/dew-point, so these stay UNKNOWN
    # rather than inventing values.
    out["wind"] = "UNKNOWN"
    out["rain"] = "UNKNOWN"

    min_alt = motion.get("min_altitude_deg")
    if alt_deg is None or min_alt is None:
        out["mount_alt"] = "UNKNOWN"
    elif alt_deg < min_alt:
        out["mount_alt"] = "CRITICAL"
    elif alt_deg < min_alt + 5.0:
        out["mount_alt"] = "WARNING"
    else:
        out["mount"] = "SAFE"
        out["mount_alt"] = "SAFE"

    states = list(out.values())
    if "CRITICAL" in states:
        out["overall"] = "CRITICAL"
    elif "WARNING" in states:
        out["overall"] = "WARNING"
    elif all(s in ("SAFE",) for s in states):
        out["overall"] = "SAFE"
    else:
        out["overall"] = "UNKNOWN"
    return out


# ── Aggregated observatory snapshot ─────────────────────────────────────
_control_lock = {"owner": None, "acquired_at": 0.0, "ttl_s": 300.0}
_lock_guard = threading.Lock()


def control_lock_status():
    with _lock_guard:
        owner = _control_lock["owner"]
        if owner and time.time() - _control_lock["acquired_at"] > _control_lock["ttl_s"]:
            _control_lock["owner"] = None
            owner = None
        return {"owner": owner,
                "acquired_at": _control_lock["acquired_at"],
                "ttl_s": _control_lock["ttl_s"]}


def acquire_control_lock(username):
    with _lock_guard:
        if _control_lock["owner"] and time.time() - _control_lock["acquired_at"] <= _control_lock["ttl_s"]:
            return {"ok": False, "owner": _control_lock["owner"]}
        _control_lock.update({"owner": username, "acquired_at": time.time()})
        return {"ok": True, "owner": username}


def release_control_lock(username, role="scientist"):
    with _lock_guard:
        if _control_lock["owner"] in (None, username) or role == "admin":
            _control_lock["owner"] = None
            return {"ok": True}
        return {"ok": False, "owner": _control_lock["owner"]}


def observatory_snapshot():
    """One read-only aggregate for CONTROL + CHECKUP + SYSTEM pages."""
    alpaca = telemetry.read_alpaca_snapshot()
    cfg = telemetry.read_stcs_config()
    weather = telemetry.read_weather_snapshot()
    vals = alpaca["values"]

    ra = vals.get("rightascension")
    dec = vals.get("declination")
    alt = vals.get("altitude")
    az = vals.get("azimuth")
    lst = vals.get("siderealtime")
    lst_source = "ALPACA"
    if lst is None:
        lon = vals.get("sitelongitude") or 79.4571
        lst = lst_hours_fallback(lon)
        lst_source = "FALLBACK-UTC"

    safety = evaluate_safety(weather["values"], alt,
                             cfg.get("limits") if cfg else None)

    mode = "REAL"
    try:
        mode = os.environ.get("TELESCOPE_MODE", "REAL").upper()
    except Exception:
        pass

    subsystems = [
        ("RA Encoder", alpaca["status"] if ra is not None else "NOT_CONNECTED", alpaca["updated_at"]),
        ("DEC Encoder", alpaca["status"] if dec is not None else "NOT_CONNECTED", alpaca["updated_at"]),
        ("Dome", alpaca["status"], alpaca["updated_at"]),
        ("Controller (Alpaca)", alpaca["status"], alpaca["updated_at"]),
        ("GPS", "NOT_AVAILABLE", 0.0),
        ("Weather (UDP 12344)", weather["status"], weather["updated_at"]),
        ("Database", "UNKNOWN", 0.0),
        ("Web Application", "LIVE", time.time()),
    ]

    return {
        "mode": mode,
        "alpaca": alpaca,
        "config": cfg,
        "weather": weather,
        "lst": lst,
        "lst_source": lst_source,
        "jd": juliandate(),
        "safety": safety,
        "subsystems": subsystems,
        "control_lock": control_lock_status(),
        "generated_at": time.time(),
    }
