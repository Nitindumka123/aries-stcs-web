"""
Read-only telemetry integration layer — Phase 2.

WHY this module exists:
  The browser must never speak the STCS hardware protocols directly.
  This module is the single read-only boundary between the web app and
  the existing STCS V1 telemetry sources:

    1. ASCOM Alpaca HTTP server (default 127.0.0.1:11111) — read-only GETs
       for RA/DEC/LST/Alt/Az/tracking/slewing/park/home + site lat/lon/elev.
    2. STCS JSON config (stcs_v1/config/limits.json, settings.json,
       state.json) — authoritative safety limits, site, offsets.
    3. Weather UDP broadcasts (default port 12344, "temp,humidity,dew_point"
       CSV datagrams) — listened to passively, never polled.

WHAT it never does:
  - Never sends Alpaca PUTs, WebSocket commands, serial bytes, or relay
    payloads. All *command* paths live behind the validated command gate
    in routes.py, which is disabled by default (STCS_COMMANDS_ENABLED=0).

Failure semantics: every source returns (value, status, updated_at).
Statuses: LIVE / STALE / NOT_CONNECTED / NOT_AVAILABLE / UNKNOWN.
The UI must render these states, never fabricate values.
"""

import json
import os
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STCS_CONFIG_DIR = os.environ.get(
    "STCS_CONFIG_DIR", os.path.join(PROJECT_ROOT, "stcs_v1", "config")
)

ALPACA_HOST = os.environ.get("ALPACA_HOST", "127.0.0.1")
ALPACA_PORT = int(os.environ.get("ALPACA_PORT", "11111"))
ALPACA_TIMEOUT_S = float(os.environ.get("ALPACA_TIMEOUT_S", "0.5"))
# WHY a short TTL cache: the snapshot polls ~14 Alpaca properties
# sequentially; without caching, every page load + API poll would pay up to
# 14 × timeout when Alpaca is down. The UI polls at ~1Hz, so a 2s cache
# keeps displayed staleness honest (updated_at is exposed) while bounding
# worst-case page latency.
ALPACA_CACHE_TTL_S = float(os.environ.get("ALPACA_CACHE_TTL_S", "2.0"))
_alpaca_cache = {"at": 0.0, "data": None}
_alpaca_lock = threading.Lock()
WEATHER_PORT = int(os.environ.get("WEATHER_PORT", "12344"))
STALE_AFTER_S = float(os.environ.get("TELEMETRY_STALE_AFTER_S", "5.0"))

_ALPACA_PROPS = [
    "rightascension",
    "declination",
    "siderealtime",
    "altitude",
    "azimuth",
    "tracking",
    "slewing",
    "athome",
    "atpark",
    "utcdate",
    "sitelatitude",
    "sitelongitude",
    "siteelevation",
    "targetrightascension",
    "targetdeclination",
]

# ── Weather UDP listener (passive cache) ────────────────────────────────
_weather_cache = {"payload": None, "updated_at": 0.0, "status": "NOT_CONNECTED"}
_weather_lock = threading.Lock()
_weather_thread = None


def _weather_loop(port: int):
    """Listen passively for 'temp,humidity,dew_point' CSV datagrams."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(1.0)
    except OSError:
        with _weather_lock:
            _weather_cache["status"] = "NOT_AVAILABLE"
        return
    with _weather_lock:
        _weather_cache["status"] = "LISTENING"
    while True:
        try:
            data, _ = sock.recvfrom(1024)
            text = data.decode("utf-8", errors="ignore").strip()
            parts = [p.strip() for p in text.split(",")]
            if len(parts) >= 2:
                payload = {
                    "temp_c": _safe_float(parts[0]),
                    "humidity_pct": _safe_float(parts[1]),
                    "dew_point_c": _safe_float(parts[2]) if len(parts) > 2 else None,
                    "raw": text,
                }
                with _weather_lock:
                    _weather_cache.update(
                        {"payload": payload, "updated_at": time.time(),
                         "status": "LIVE"}
                    )
        except socket.timeout:
            continue
        except Exception:
            time.sleep(0.5)


def ensure_weather_listener():
    """Start the passive UDP listener once (idempotent)."""
    global _weather_thread
    if _weather_thread is None or not _weather_thread.is_alive():
        _weather_thread = threading.Thread(
            target=_weather_loop, args=(WEATHER_PORT,), daemon=True
        )
        _weather_thread.start()


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _alpaca_get(prop_name: str):
    """Single read-only Alpaca GET. Returns (value, ok)."""
    url = (
        f"http://{ALPACA_HOST}:{ALPACA_PORT}"
        f"/api/v1/telescope/0/{prop_name}"
    )
    try:
        with urllib.request.urlopen(url, timeout=ALPACA_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ErrorNumber", 0) != 0:
            return None, False
        return body.get("Value"), True
    except Exception:
        return None, False


def _alpaca_reachable():
    """Fail-fast TCP probe so a down Alpaca server costs ~ms, not 14 timeouts.

    WHY: each property GET has its own timeout; when nothing listens on the
    Alpaca port the kernel refuses instantly, but a hanging host would stall
    every page render. One short probe decides before the full poll.
    """
    try:
        sock = socket.create_connection((ALPACA_HOST, ALPACA_PORT), timeout=0.3)
        sock.close()
        return True
    except OSError:
        return False


def read_alpaca_snapshot():
    """Poll all read-only Alpaca properties. Never sends PUTs."""
    with _alpaca_lock:
        if (_alpaca_cache["data"] is not None
                and time.time() - _alpaca_cache["at"] < ALPACA_CACHE_TTL_S):
            return _alpaca_cache["data"]
    if not _alpaca_reachable():
        now = time.time()
        data = {"values": {p: None for p in _ALPACA_PROPS},
                "status": "NOT_CONNECTED", "updated_at": now}
        with _alpaca_lock:
            _alpaca_cache.update({"at": now, "data": data})
        return data
    values, ok_any, ok_all = {}, False, True
    for prop in _ALPACA_PROPS:
        value, ok = _alpaca_get(prop)
        values[prop] = value
        ok_any = ok_any or ok
        ok_all = ok_all and ok
    now = time.time()
    status = "LIVE" if ok_all else ("STALE" if ok_any else "NOT_CONNECTED")
    data = {"values": values, "status": status, "updated_at": now}
    with _alpaca_lock:
        _alpaca_cache.update({"at": now, "data": data})
    return data


def read_stcs_config():
    """Read authoritative STCS JSON config (limits/site/offsets)."""
    out = {"limits": None, "settings": None, "state": None, "status": "UNKNOWN"}
    try:
        for key, fname in (
            ("limits", "limits.json"),
            ("settings", "settings.json"),
            ("state", "state.json"),
        ):
            path = os.path.join(STCS_CONFIG_DIR, fname)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    out[key] = json.load(fh)
        out["status"] = "LIVE" if out["limits"] else "NOT_AVAILABLE"
    except Exception:
        out["status"] = "NOT_AVAILABLE"
    out["updated_at"] = time.time()
    return out


def read_weather_snapshot():
    """Return the last passively-received weather datagram with staleness."""
    ensure_weather_listener()
    with _weather_lock:
        cache = dict(_weather_cache)
    age = time.time() - cache.get("updated_at", 0.0)
    payload = cache.get("payload")
    if payload is None:
        status = "NOT_CONNECTED" if cache.get("status") != "NOT_AVAILABLE" else "NOT_AVAILABLE"
    else:
        status = "LIVE" if age <= STALE_AFTER_S else "STALE"
    return {"values": payload, "status": status, "age_s": age,
            "updated_at": cache.get("updated_at", 0.0)}


def snapshot_status(age_s: float, connected: bool):
    """Classify a cached value as LIVE / STALE / NOT_CONNECTED."""
    if not connected:
        return "NOT_CONNECTED"
    if age_s <= STALE_AFTER_S:
        return "LIVE"
    return "STALE"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
