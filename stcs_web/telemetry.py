"""
Read-only telemetry integration layer — Phase 2.

WHY this module exists:
  The browser must never speak the STCS hardware protocols directly.
  This module is the single read-only boundary between the web app and
  the existing STCS V1 telemetry sources:

    1. ASCOM Alpaca HTTP server (default 127.0.0.1:11111) — read-only GETs
       for RA/DEC/LST/Alt/Az/tracking/slewing/park/home + site lat/lon/elev.
    2. STCS WebSocket Telemetry Server (default 127.0.0.1:11112) — read-only
       WebSocket client receiving 10Hz telemetry broadcasts with motion state,
       dome state, tracking, safety limits, and weather.
    3. STCS JSON config (stcs_v1/config/limits.json, settings.json,
       state.json) — authoritative safety limits, site, offsets.

WHAT it never does:
  - Never sends Alpaca PUTs, WebSocket commands, serial bytes, or relay
    payloads. All *command* paths live behind the validated command gate
    in routes.py, which is disabled by default (STCS_COMMANDS_ENABLED=0).
  - Never binds to UDP port 12344 (weather) to avoid conflict with
    stcs_v1 WeatherWorker which owns that port.

Failure semantics: every source returns (value, status, updated_at).
Statuses: LIVE / STALE / DISCONNECTED / NOT_AVAILABLE / UNKNOWN.
The UI must render these states, never fabricate values.
"""

import asyncio
import json
import os
import socket
import threading
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

import websockets

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STCS_CONFIG_DIR = os.environ.get(
    "STCS_CONFIG_DIR", os.path.join(PROJECT_ROOT, "stcs_v1", "config")
)

ALPACA_HOST = os.environ.get("ALPACA_HOST", "127.0.0.1")
ALPACA_PORT = int(os.environ.get("ALPACA_PORT", "11111"))
ALPACA_TIMEOUT_S = float(os.environ.get("ALPACA_TIMEOUT_S", "0.5"))
ALPACA_CACHE_TTL_S = float(os.environ.get("ALPACA_CACHE_TTL_S", "2.0"))

TELEMETRY_WS_HOST = os.environ.get("TELEMETRY_WS_HOST", "127.0.0.1")
TELEMETRY_WS_PORT = int(os.environ.get("TELEMETRY_WS_PORT", "11112"))
TELEMETRY_WS_URL = f"ws://{TELEMETRY_WS_HOST}:{TELEMETRY_WS_PORT}/ws/telemetry"
WS_RECONNECT_DELAY_S = float(os.environ.get("WS_RECONNECT_DELAY_S", "3.0"))
WS_CONNECT_TIMEOUT_S = float(os.environ.get("WS_CONNECT_TIMEOUT_S", "5.0"))

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

# ── Alpaca HTTP cache ──────────────────────────────────────────────────────
_alpaca_cache: Dict[str, Any] = {"at": 0.0, "data": None}
_alpaca_lock = threading.Lock()

# ── WebSocket telemetry cache ──────────────────────────────────────────────
_ws_cache: Dict[str, Any] = {
    "payload": None,
    "updated_at": 0.0,
    "status": "NOT_CONNECTED",
    "last_error": None,
}
_ws_lock = threading.Lock()
_ws_thread: Optional[threading.Thread] = None
_ws_stop_event: Optional[threading.Event] = None
_ws_loop: Optional[asyncio.AbstractEventLoop] = None

# ── Config cache ───────────────────────────────────────────────────────────
_config_cache: Dict[str, Any] = {"at": 0.0, "data": None, "status": "UNKNOWN"}
_config_lock = threading.Lock()
_CONFIG_CACHE_TTL_S = 30.0


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _alpaca_get(prop_name: str) -> tuple[Optional[Any], bool]:
    """Single read-only Alpaca GET. Returns (value, ok)."""
    url = f"http://{ALPACA_HOST}:{ALPACA_PORT}/api/v1/telescope/0/{prop_name}"
    try:
        with urllib.request.urlopen(url, timeout=ALPACA_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ErrorNumber", 0) != 0:
            return None, False
        return body.get("Value"), True
    except Exception:
        return None, False


def _alpaca_reachable() -> bool:
    """Fail-fast TCP probe so a down Alpaca server costs ~ms, not 14 timeouts."""
    try:
        sock = socket.create_connection((ALPACA_HOST, ALPACA_PORT), timeout=0.3)
        sock.close()
        return True
    except OSError:
        return False


def read_alpaca_snapshot() -> Dict[str, Any]:
    """Poll all read-only Alpaca properties. Never sends PUTs."""
    with _alpaca_lock:
        if (
            _alpaca_cache["data"] is not None
            and time.time() - _alpaca_cache["at"] < ALPACA_CACHE_TTL_S
        ):
            return _alpaca_cache["data"]

    if not _alpaca_reachable():
        now = time.time()
        data = {
            "values": {p: None for p in _ALPACA_PROPS},
            "status": "NOT_CONNECTED",
            "updated_at": now,
        }
        with _alpaca_lock:
            _alpaca_cache.update({"at": now, "data": data})
        return data

    values: Dict[str, Any] = {}
    ok_any = False
    ok_all = True
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


def read_stcs_config() -> Dict[str, Any]:
    """Read authoritative STCS JSON config (limits/site/offsets)."""
    with _config_lock:
        if (
            _config_cache["data"] is not None
            and time.time() - _config_cache["at"] < _CONFIG_CACHE_TTL_S
        ):
            return _config_cache["data"]

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
    with _config_lock:
        _config_cache.update({"at": time.time(), "data": out})
    return out


# ── WebSocket telemetry client ─────────────────────────────────────────────
async def _ws_client_loop(stop_event: threading.Event):
    """Async WebSocket client loop running in a dedicated thread with its own event loop."""
    global _ws_loop
    _ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_ws_loop)

    try:
        await _ws_client_inner(stop_event)
    finally:
        _ws_loop.close()
        _ws_loop = None


async def _ws_client_inner(stop_event: threading.Event):
    """Inner async loop for WebSocket connection with reconnection logic."""
    while not stop_event.is_set():
        try:
            async with websockets.connect(
                TELEMETRY_WS_URL,
                open_timeout=WS_CONNECT_TIMEOUT_S,
                ping_interval=10,
                ping_timeout=5,
            ) as ws:
                with _ws_lock:
                    _ws_cache.update(
                        {"status": "LIVE", "last_error": None, "updated_at": time.time()}
                    )

                async for message in ws:
                    if stop_event.is_set():
                        break
                    try:
                        data = json.loads(message)
                        if data.get("type") == "telemetry":
                            with _ws_lock:
                                _ws_cache.update(
                                    {
                                        "payload": data,
                                        "updated_at": time.time(),
                                        "status": "LIVE",
                                        "last_error": None,
                                    }
                                )
                    except json.JSONDecodeError:
                        pass
                    except Exception:
                        pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            with _ws_lock:
                _ws_cache.update(
                    {"status": "NOT_CONNECTED", "last_error": str(e), "updated_at": time.time()}
                )

        # Reconnection delay
        if not stop_event.is_set():
            await asyncio.sleep(WS_RECONNECT_DELAY_S)


def ensure_ws_listener():
    """Start the WebSocket telemetry client once (idempotent)."""
    global _ws_thread, _ws_stop_event
    if _ws_thread is not None and _ws_thread.is_alive():
        return

    _ws_stop_event = threading.Event()
    _ws_thread = threading.Thread(
        target=lambda: asyncio.run(_ws_client_loop(_ws_stop_event)),
        daemon=True,
    )
    _ws_thread.start()


def stop_ws_listener():
    """Stop the WebSocket telemetry client."""
    global _ws_thread, _ws_stop_event
    if _ws_stop_event:
        _ws_stop_event.set()
    if _ws_thread:
        _ws_thread.join(timeout=2.0)
        _ws_thread = None
    _ws_stop_event = None


def read_ws_snapshot() -> Dict[str, Any]:
    """Return the last WebSocket telemetry broadcast with staleness."""
    ensure_ws_listener()
    with _ws_lock:
        cache = dict(_ws_cache)

    age = time.time() - cache.get("updated_at", 0.0)
    payload = cache.get("payload")
    status = cache.get("status", "NOT_CONNECTED")

    if payload is None:
        if status == "NOT_CONNECTED":
            pass  # keep NOT_CONNECTED
        else:
            status = "NOT_CONNECTED"
    else:
        if age <= STALE_AFTER_S:
            status = "LIVE"
        else:
            status = "STALE"

    return {
        "values": payload,
        "status": status,
        "age_s": age,
        "updated_at": cache.get("updated_at", 0.0),
        "last_error": cache.get("last_error"),
    }


def snapshot_status(age_s: float, connected: bool) -> str:
    """Classify a cached value as LIVE / STALE / NOT_CONNECTED."""
    if not connected:
        return "NOT_CONNECTED"
    if age_s <= STALE_AFTER_S:
        return "LIVE"
    return "STALE"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()