"""
Observatory service layer — Production weather architecture.

WHY: templates must never speak hardware protocols. This module turns the
raw read-only snapshots from telemetry.py into clean domain data:
  - mount/dome/tracking/system status with LIVE/STALE/NOT_CONNECTED states
  - safety evaluation using thresholds already defined in
    stcs_v1/config/limits.json (never invented here)
  - astronomical formatting (RA HMS, DEC DMS, LST, JD) for the POSITION tab
  - subsystem health matrix for CHECKUP/SYSTEM
  - weather data model with source/freshness/availability transparency

WEATHER ARCHITECTURE:
  The existing STCS V1 WeatherWorker receives UDP packets on port 12344
  containing: temp_c,humidity_percent,dew_point_c (ASCII CSV).

  This web layer consumes weather data via the STCS WebSocket telemetry
  server (port 11112), which embeds weather in its broadcast payload.

  The web layer NEVER binds to UDP 12344 directly.

  Weather source: ARIES Manora Peak Weather Station (via STCS WeatherWorker)
  Protocol: UDP port 12344 → STCS WebSocket → Web telemetry adapter

  Available fields: temp_c, humidity_pct, dew_point_c
  Unavailable fields: wind_speed, wind_direction, rain, pressure (no hardware)

No commands are issued from this module. No values are fabricated: when a
source is unavailable the field is None and the status explains why.
"""

import math
import os
import time
from datetime import datetime, timezone

from . import telemetry
from . import control_lock


# ── Weather source identification ─────────────────────────────────────
WEATHER_SOURCE = "ARIES Manora Peak Weather Station"
WEATHER_PROTOCOL = "UDP 12344 → STCS WeatherWorker → WebSocket 11112"
WEATHER_FIELDS_AVAILABLE = ["temp_c", "humidity_pct", "dew_point_c"]
WEATHER_FIELDS_UNAVAILABLE = ["wind_speed_kmh", "wind_direction", "rain", "pressure_hpa"]
WEATHER_STALE_THRESHOLD_S = 30.0  # Weather data older than this is STALE
WEATHER_DISCONNECTED_THRESHOLD_S = 120.0  # Weather data older than this is DISCONNECTED


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
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5


def lst_hours_fallback(lon_deg=79.4571):
    """GMST-based LST fallback used ONLY when all telemetry sources lack LST."""
    now = datetime.now(timezone.utc)
    jd = juliandate(now)
    d = jd - 2451545.0
    gmst = (18.697374558 + 24.06570982441908 * d) % 24.0
    return (gmst + lon_deg / 15.0) % 24.0


def _fmt_age(age_s):
    """Format age in human-readable form."""
    if age_s is None or age_s <= 0:
        return "—"
    if age_s < 60:
        return f"{age_s:.0f}s"
    if age_s < 3600:
        return f"{age_s/60:.1f}m"
    return f"{age_s/3600:.1f}h"


# Control lock functions (delegated to shared module)
control_lock_status = control_lock.control_lock_status
acquire_control_lock = control_lock.acquire_control_lock
release_control_lock = control_lock.release_control_lock

# ── Weather freshness evaluation ───────────────────────────────────────
def evaluate_weather_freshness(weather_data, ws_status, ws_age_s):
    """Evaluate weather data freshness independently from WS telemetry.

    The STCS WeatherWorker receives UDP packets at an unknown rate.
    We track weather freshness based on:
    1. Whether weather data exists in the WS payload
    2. The age of the last WS broadcast (proxy for weather age)
    3. The WS connection status

    Returns: (weather_status, weather_age_s, weather_source, weather_detail)
    """
    if weather_data is None:
        return "NOT_AVAILABLE", 0.0, WEATHER_SOURCE, "No weather data in telemetry payload"

    if ws_status == "NOT_CONNECTED":
        return "DISCONNECTED", ws_age_s, WEATHER_SOURCE, "WebSocket telemetry disconnected"

    if ws_age_s > WEATHER_DISCONNECTED_THRESHOLD_S:
        return "DISCONNECTED", ws_age_s, WEATHER_SOURCE, f"Last update {_fmt_age(ws_age_s)} ago"

    if ws_age_s > WEATHER_STALE_THRESHOLD_S:
        return "STALE", ws_age_s, WEATHER_SOURCE, f"Last update {_fmt_age(ws_age_s)} ago"

    return "LIVE", ws_age_s, WEATHER_SOURCE, f"Updated {_fmt_age(ws_age_s)} ago"


# ── Safety evaluation (thresholds from STCS limits.json only) ───────────
def evaluate_safety(weather, alt_deg, limits, weather_status="UNKNOWN", weather_age_s=0.0):
    """Return per-parameter safety states. Unknown when data is missing.

    Thresholds come from stcs_v1/config/limits.json environment section:
      max_humidity_percent, max_wind_speed_kmh, close_dome_on_rain,
      motion.min_altitude_deg. Nothing is invented here.

    IMPORTANT: This evaluates CONFIGURED thresholds, NOT active safety interlocks.
    The existing STCS V1 WeatherWorker has safety checks COMMENTED OUT.
    The web layer evaluates thresholds for DISPLAY purposes only.
    Actual safety enforcement remains in the authoritative STCS V1 system.
    """
    env = (limits or {}).get("environment", {}) if limits else {}
    motion = (limits or {}).get("motion", {}) if limits else {}
    out = {}

    # ── Weather freshness ──
    out["weather_data"] = weather_status

    # ── Humidity ──
    hum = (weather or {}).get("humidity_pct")
    max_hum = env.get("max_humidity_percent")
    if hum is None:
        out["humidity"] = "NOT_AVAILABLE"
    elif max_hum is None:
        out["humidity"] = "NOT_CONFIGURED"
    elif hum >= max_hum:
        out["humidity"] = "CRITICAL"
    elif hum >= max_hum - 10.0:
        out["humidity"] = "WARNING"
    else:
        out["humidity"] = "SAFE"

    # ── Temperature ──
    temp = (weather or {}).get("temp_c")
    if temp is None:
        out["temperature"] = "NOT_AVAILABLE"
    else:
        out["temperature"] = "OK"

    # ── Dew point ──
    dew = (weather or {}).get("dew_point_c")
    if dew is None:
        out["dew_point"] = "NOT_AVAILABLE"
    else:
        out["dew_point"] = "OK"

    # ── Wind ──
    # The existing STCS WeatherWorker does NOT receive wind data.
    # limits.json defines max_wind_speed_kmh but no hardware provides it.
    wind_speed = (weather or {}).get("wind_speed_kmh")
    max_wind = env.get("max_wind_speed_kmh")
    if wind_speed is None:
        out["wind"] = "NOT_AVAILABLE"
    elif max_wind is None:
        out["wind"] = "NOT_CONFIGURED"
    elif wind_speed >= max_wind:
        out["wind"] = "CRITICAL"
    elif wind_speed >= max_wind * 0.75:
        out["wind"] = "WARNING"
    else:
        out["wind"] = "SAFE"

    # ── Rain ──
    # The existing STCS WeatherWorker does NOT receive rain data.
    # limits.json defines close_dome_on_rain but no hardware provides it.
    rain = (weather or {}).get("rain")
    if rain is None:
        out["rain"] = "NOT_AVAILABLE"
    else:
        rain_flag = env.get("close_dome_on_rain", False)
        if not rain_flag:
            out["rain"] = "NOT_CONFIGURED"
        elif rain:
            out["rain"] = "CRITICAL"
        else:
            out["rain"] = "SAFE"

    # ── Mount altitude ──
    min_alt = motion.get("min_altitude_deg")
    max_alt = motion.get("max_altitude_deg")
    if alt_deg is None:
        out["mount_alt"] = "NOT_AVAILABLE"
    elif min_alt is not None and alt_deg < min_alt:
        out["mount_alt"] = "CRITICAL"
    elif min_alt is not None and alt_deg < min_alt + 5.0:
        out["mount_alt"] = "WARNING"
    elif max_alt is not None and alt_deg > max_alt:
        out["mount_alt"] = "WARNING"
    else:
        out["mount_alt"] = "SAFE"

    # ── Overall safety ──
    states = list(out.values())
    if "CRITICAL" in states:
        out["overall"] = "CRITICAL"
    elif "WARNING" in states:
        out["overall"] = "WARNING"
    elif all(s in ("SAFE", "OK", "LIVE") for s in states):
        out["overall"] = "SAFE"
    elif "NOT_AVAILABLE" in states or "DISCONNECTED" in states or "NOT_CONFIGURED" in states:
        out["overall"] = "UNKNOWN"
    else:
        out["overall"] = "UNKNOWN"
    return out


def observatory_snapshot():
    """One read-only aggregate for CONTROL + CHECKUP + SYSTEM pages.

    Priority order for telemetry:
    1. WebSocket Telemetry Server (port 11112) — richest data including
       motion state, dome, tracking, safety limits, weather
    2. Alpaca HTTP (port 11111) — basic coordinates and site info
    3. Config files — limits, settings, state (offsets)
    """
    # Primary: WebSocket telemetry (richest)
    ws = telemetry.read_ws_snapshot()
    # Fallback: Alpaca HTTP
    alpaca = telemetry.read_alpaca_snapshot()
    # Config
    cfg = telemetry.read_stcs_config()

    ws_vals = ws.get("values") or {}
    alpaca_vals = alpaca.get("values") or {}

    # ── Coordinates: prefer WebSocket, fall back to Alpaca ──
    ra = ws_vals.get("ra_hours", alpaca_vals.get("rightascension"))
    dec = ws_vals.get("dec_deg", alpaca_vals.get("declination"))
    ha = ws_vals.get("ha_hours")
    lst = ws_vals.get("lst_hours", alpaca_vals.get("siderealtime"))
    alt = ws_vals.get("alt_deg", alpaca_vals.get("altitude"))
    az = ws_vals.get("az_deg", alpaca_vals.get("azimuth"))

    # Determine LST source for display
    lst_source = "WS" if ws_vals.get("lst_hours") is not None else "ALPACA"
    if lst is None:
        lon = alpaca_vals.get("sitelongitude") or 79.4571
        lst = lst_hours_fallback(lon)
        lst_source = "FALLBACK-UTC"

    # ── Weather: prefer WebSocket (includes weather from STCS) ──
    weather_data = ws_vals.get("weather")
    if weather_data:
        weather = {"values": weather_data, "status": ws["status"], "age_s": ws["age_s"], "updated_at": ws["updated_at"]}
    else:
        weather = {"values": None, "status": "NOT_AVAILABLE", "age_s": 0.0, "updated_at": 0.0}

    # ── Motion/Dome/Tracking state from WebSocket ──
    tracking = ws_vals.get("tracking")
    slewing = ws_vals.get("is_slewing")
    ra_speed = ws_vals.get("ra_speed")
    ra_direction = ws_vals.get("ra_direction")
    dec_speed = ws_vals.get("dec_speed")
    dec_direction = ws_vals.get("dec_direction")
    dome_state = ws_vals.get("dome_state")
    dome_az = ws_vals.get("dome_az_deg")
    safety_limit_active = ws_vals.get("safety_limit_active")
    safety_limit_message = ws_vals.get("safety_limit_message")
    cooldown_active = ws_vals.get("cooldown_active")
    mode = ws_vals.get("mode", "REAL")

    # Fallback to Alpaca for tracking/slewing if WS unavailable
    if tracking is None:
        tracking = alpaca_vals.get("tracking")
    if slewing is None:
        slewing = alpaca_vals.get("slewing")

    # ── Weather freshness evaluation ──
    wx_status, wx_age, wx_source, wx_detail = evaluate_weather_freshness(
        weather_data, ws["status"], ws["age_s"]
    )

    # ── Safety evaluation ──
    safety = evaluate_safety(
        weather["values"], alt, cfg.get("limits") if cfg else None,
        weather_status=wx_status, weather_age_s=wx_age
    )

    # Override with explicit safety limit from WebSocket if present
    if safety_limit_active:
        safety["mount_alt"] = "CRITICAL"
        safety["overall"] = "CRITICAL"

    # ── Mode ──
    try:
        mode = os.environ.get("TELESCOPE_MODE", mode).upper()
    except Exception:
        pass

    # ── Subsystem health matrix ──
    telemetry_status = ws["status"] if ws["status"] != "NOT_CONNECTED" else alpaca["status"]

    subsystems = [
        ("RA Encoder", telemetry_status if ra is not None else "NOT_CONNECTED",
         ws["updated_at"] if ws["status"] != "NOT_CONNECTED" else alpaca["updated_at"]),
        ("DEC Encoder", telemetry_status if dec is not None else "NOT_CONNECTED",
         ws["updated_at"] if ws["status"] != "NOT_CONNECTED" else alpaca["updated_at"]),
        ("Dome", telemetry_status if dome_az is not None else "NOT_CONNECTED",
         ws["updated_at"] if ws["status"] != "NOT_CONNECTED" else alpaca["updated_at"]),
        ("Controller (WS/Alpaca)", telemetry_status,
         ws["updated_at"] if ws["status"] != "NOT_CONNECTED" else alpaca["updated_at"]),
        ("GPS", "NOT_AVAILABLE", 0.0),
        ("Weather (STCS)", wx_status, weather["updated_at"]),
        ("Database", "UNKNOWN", 0.0),
        ("Web Application", "LIVE", time.time()),
    ]

    return {
        "mode": mode,
        "alpaca": alpaca,
        "ws": ws,
        "config": cfg,
        "weather": weather,
        "lst": lst,
        "lst_source": lst_source,
        "jd": juliandate(),
        "safety": safety,
        "subsystems": subsystems,
        "control_lock": control_lock_status(),
        "generated_at": time.time(),
        # Rich telemetry fields for templates
        "ra_hours": ra,
        "dec_deg": dec,
        "ha_hours": ha,
        "lst_hours": lst,
        "alt_deg": alt,
        "az_deg": az,
        "dome_az_deg": dome_az,
        "tracking": tracking,
        "slewing": slewing,
        "ra_speed": ra_speed,
        "ra_direction": ra_direction,
        "dec_speed": dec_speed,
        "dec_direction": dec_direction,
        "dome_state": dome_state,
        "safety_limit_active": safety_limit_active,
        "safety_limit_message": safety_limit_message,
        "cooldown_active": cooldown_active,
        "telemetry_status": telemetry_status,
        "telemetry_source": "WS" if ws["status"] != "NOT_CONNECTED" else ("ALPACA" if alpaca["status"] != "NOT_CONNECTED" else "NONE"),
        # Detailed environment breakdown
        "environment": _build_environment(weather, alt, cfg, safety_limit_active, cooldown_active,
                                           wx_status, wx_age, wx_source, wx_detail),
    }


def _build_environment(weather, alt_deg, cfg, safety_limit_active, cooldown_active,
                        wx_status="UNKNOWN", wx_age_s=0.0, wx_source="", wx_detail=""):
    """Build detailed environment/safety breakdown for templates.

    Exposes existing STCS state honestly. Does NOT invent safety actions.

    Weather source transparency:
    - Source: ARIES Manora Peak Weather Station (via STCS WeatherWorker)
    - Protocol: UDP 12344 → STCS WebSocket 11112
    - Available: temp_c, humidity_pct, dew_point_c
    - Unavailable: wind, rain, pressure (no hardware connected)
    """
    wvals = weather.get("values") or {}
    env_thresholds = ((cfg or {}).get("limits") or {}).get("environment", {})
    motion_limits = ((cfg or {}).get("limits") or {}).get("motion", {})

    # Weather values
    temp = wvals.get("temp_c")
    humidity = wvals.get("humidity_pct")
    dewpoint = wvals.get("dew_point_c")
    wind = wvals.get("wind_speed_kmh")
    rain = wvals.get("rain")

    # Thresholds from limits.json
    max_hum = env_thresholds.get("max_humidity_percent")
    max_wind = env_thresholds.get("max_wind_speed_kmh")
    rain_policy = env_thresholds.get("close_dome_on_rain")
    min_alt = motion_limits.get("min_altitude_deg")
    max_alt = motion_limits.get("max_altitude_deg")

    # Humidity state
    if humidity is None:
        hum_state = "NOT_AVAILABLE"
    elif max_hum is None:
        hum_state = "NOT_CONFIGURED"
    elif humidity >= max_hum:
        hum_state = "CRITICAL"
    elif humidity >= max_hum - 10.0:
        hum_state = "WARNING"
    else:
        hum_state = "SAFE"

    # Wind state
    if wind is None:
        wind_state = "NOT_AVAILABLE"
    elif max_wind is None:
        wind_state = "NOT_CONFIGURED"
    elif wind >= max_wind:
        wind_state = "CRITICAL"
    elif wind >= max_wind * 0.75:
        wind_state = "WARNING"
    else:
        wind_state = "SAFE"

    # Rain state
    if rain is None:
        rain_state = "NOT_AVAILABLE"
    elif not rain_policy:
        rain_state = "NOT_CONFIGURED"
    elif rain:
        rain_state = "CRITICAL"
    else:
        rain_state = "SAFE"

    # Altitude state
    if alt_deg is None:
        alt_state = "NOT_AVAILABLE"
    elif min_alt is not None and alt_deg < min_alt:
        alt_state = "CRITICAL"
    elif min_alt is not None and alt_deg < min_alt + 5.0:
        alt_state = "WARNING"
    elif max_alt is not None and alt_deg > max_alt:
        alt_state = "WARNING"
    else:
        alt_state = "SAFE"

    # Determine if safety interlock is ACTIVE (configured) vs IMPLEMENTED
    # The STCS V1 WeatherWorker has humidity safety COMMENTED OUT
    # limits.json environment section is NEVER LOADED by STCS V1 code
    # Therefore: these are CONFIGURED thresholds, NOT active interlocks
    hum_interlock_active = False  # STCS V1 has this commented out
    wind_interlock_active = False  # No wind hardware
    rain_interlock_active = False  # No rain hardware

    return {
        # Weather values
        "temperature": temp,
        "humidity": humidity,
        "dew_point": dewpoint,
        "wind_speed": wind,
        "rain": rain,
        # Weather source transparency
        "weather_status": wx_status,
        "weather_age_s": wx_age_s,
        "weather_age_fmt": _fmt_age(wx_age_s),
        "weather_source": wx_source,
        "weather_detail": wx_detail,
        "weather_fields_available": WEATHER_FIELDS_AVAILABLE,
        "weather_fields_unavailable": WEATHER_FIELDS_UNAVAILABLE,
        # Safety states (CONFIGURED thresholds)
        "humidity_state": hum_state,
        "humidity_threshold": max_hum,
        "humidity_interlock_active": hum_interlock_active,
        "wind_state": wind_state,
        "wind_threshold": max_wind,
        "wind_interlock_active": wind_interlock_active,
        "rain_state": rain_state,
        "rain_policy": rain_policy,
        "rain_interlock_active": rain_interlock_active,
        # Telescope safety
        "altitude": alt_deg,
        "altitude_state": alt_state,
        "altitude_floor": min_alt,
        "altitude_ceiling": max_alt,
        "safety_limit_active": safety_limit_active,
        "cooldown_active": cooldown_active,
        "mode": "REAL" if not cooldown_active else "COOLDOWN",
    }
