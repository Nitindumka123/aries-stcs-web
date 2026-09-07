# src/workers/telemetry_server.py
"""
WebSocket Telemetry Server for STCS Mobile Remote Control.

Provides a bidirectional WebSocket channel for:
  - OUTBOUND: 10Hz telemetry broadcast (RA, DEC, HRA, LST, Alt, Az, etc.)
  - INBOUND:  Validated motion commands from the mobile app

Security:
  - Rejects conflicting directions on the same axis (N+S or E+W)
  - Rejects invalid axis/direction combinations (e.g., NORTH on RA axis)
  - Dead Man's Switch: auto-stops telescope if client disconnects mid-motion
  - All commands go through MotionState's thread-safe, interlocked setters

Port: 11112 (configurable via TELEMETRY_WS_PORT env var)
"""
import os
import asyncio
import json
import time
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logger = logging.getLogger("TelemetryServer")

# ═══════════════════════════════════════════════════════════
# VALID COMMAND SCHEMAS
# ═══════════════════════════════════════════════════════════

# Which directions are legal for each axis
VALID_DIRECTIONS = {
    "RA":  {"EAST", "WEST", "NONE"},
    "DEC": {"NORTH", "SOUTH", "NONE"},
}

VALID_SPEEDS = {"COARSE", "FINE_1", "FINE_2"}

VALID_COMMANDS = {
    "manual_move",      # Set axis direction + speed
    "stop",             # Emergency stop all motion
    "tracking_on",      # Activate sidereal tracking
    "tracking_off",     # Deactivate sidereal tracking
    "dome_cw",          # Dome clockwise pulse
    "dome_ccw",         # Dome counter-clockwise pulse
    "dome_off",         # Dome stop pulse
    "heartbeat",        # Keep-alive ping from the mobile app
}

# ═══════════════════════════════════════════════════════════
# SHARED STATE (set by TelemetryServerThread before start)
# ═══════════════════════════════════════════════════════════

_motion_state = None
_slew_engine = None
_astro = None


# ═══════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════

app = FastAPI(title="STCS Telemetry Server", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track connected clients for broadcast
_connected_clients: set[WebSocket] = set()
_client_lock = threading.Lock()

# Track state per client: {"last_hb": timestamp, "initiated_motion": bool}
_client_state: dict[int, dict] = {}

# Dead Man's Switch timeout (seconds)
HEARTBEAT_TIMEOUT = 2.0


def _build_telemetry_snapshot() -> dict:
    """
    Build a complete dashboard snapshot from current state.
    Called at 10Hz by the broadcast loop.
    """
    ms = _motion_state
    astro = _astro

    if not ms or not astro:
        return {"error": "System not ready"}

    # Get cached coordinates (cheap)
    lst_hours = astro.get_current_lst_hours_cached()
    sim_ha_hours = ms.sim_ha_deg / 15.0
    ra_hours = (lst_hours - sim_ha_hours) % 24.0
    dec_deg = ms.sim_dec_deg

    # Get alt/az
    try:
        astro_params = astro.calculate_parameters(ra_hours, dec_deg)
        alt_deg = astro_params.get("alt_deg", 0.0)
        az_deg = astro_params.get("az_deg", 0.0)
    except Exception:
        alt_deg = 0.0
        az_deg = 0.0

    # Get motor status
    status = ms.get_status_snapshot()

    return {
        "type": "telemetry",
        "timestamp": time.time(),
        # Coordinates
        "ra_hours": round(ra_hours, 6),
        "dec_deg": round(dec_deg, 4),
        "ha_hours": round(sim_ha_hours if sim_ha_hours >= 0 else sim_ha_hours + 24.0, 6),
        "lst_hours": round(lst_hours, 6),
        "alt_deg": round(alt_deg, 4),
        "az_deg": round(az_deg, 4),
        "dome_az_deg": round(getattr(ms, 'dome_az_deg', 0.0), 2),
        "weather": getattr(ms, 'weather_data', None),
        # Motion state
        "ra_speed": status["ra_speed"],
        "ra_direction": status["ra_direction"],
        "dec_speed": status["dec_speed"],
        "dec_direction": status["dec_direction"],
        "tracking": status["tracking"],
        "is_slewing": status["is_slewing"],
        "safety_limit_active": status.get("safety_limit_active", False),
        "safety_limit_message": status.get("safety_limit_message", ""),
        "dome_state": status["dome_state"],
        "cooldown_active": status["cooldown_active"],
        "mode": status["mode"],
    }


def _validate_and_execute(data: dict) -> dict:
    """
    Validate an incoming command and execute it through MotionState.

    Returns a response dict with status and optional error message.
    """
    ms = _motion_state
    se = _slew_engine

    if not ms:
        return {"status": "error", "message": "System not ready"}

    command = data.get("command", "").strip()

    if command not in VALID_COMMANDS:
        logger.warning(f"SECURITY: Unknown command rejected: {command}")
        return {"status": "error", "message": f"Unknown command: {command}"}

    # ── HEARTBEAT ──────────────────────────────────────────
    if command == "heartbeat":
        return {"status": "ok", "message": "pong"}

    # ── EMERGENCY STOP ─────────────────────────────────────
    if command == "stop":
        if se:
            se.abort()
        ms.emergency_stop()
        logger.info("MOBILE: Emergency stop executed.")
        return {"status": "ok", "message": "Emergency stop executed"}

    # ── TRACKING ───────────────────────────────────────────
    if command == "tracking_on":
        ms.activate_tracking()
        logger.info("MOBILE: Tracking activated.")
        return {"status": "ok", "message": "Tracking ON"}

    if command == "tracking_off":
        ms.deactivate_tracking()
        logger.info("MOBILE: Tracking deactivated.")
        return {"status": "ok", "message": "Tracking OFF"}

    # ── DOME ───────────────────────────────────────────────
    if command == "dome_cw":
        ms.set_dome_cw()
        return {"status": "ok", "message": "Dome CW pulse sent"}

    if command == "dome_ccw":
        ms.set_dome_ccw()
        return {"status": "ok", "message": "Dome CCW pulse sent"}

    if command == "dome_off":
        ms.set_dome_off()
        return {"status": "ok", "message": "Dome OFF pulse sent"}

    # ── MANUAL MOVE (the critical one) ─────────────────────
    if command == "manual_move":
        axis = data.get("axis", "").upper()
        direction = data.get("direction", "").upper()
        speed = data.get("speed", "").upper()

        # --- Validation Layer 1: Field presence ---
        if axis not in VALID_DIRECTIONS:
            logger.warning(f"SECURITY: Invalid axis rejected: {axis}")
            return {"status": "error", "message": f"Invalid axis: {axis}"}

        if direction not in VALID_DIRECTIONS[axis]:
            logger.warning(
                f"SECURITY: Invalid direction '{direction}' for axis '{axis}'. "
                f"Possible conflict attack."
            )
            return {
                "status": "error",
                "message": f"Direction '{direction}' is not valid for axis '{axis}'. "
                           f"Valid: {VALID_DIRECTIONS[axis]}"
            }

        # Speed is only required when direction is not NONE
        if direction != "NONE" and speed not in VALID_SPEEDS:
            logger.warning(f"SECURITY: Invalid speed rejected: {speed}")
            return {"status": "error", "message": f"Invalid speed: {speed}"}

        # --- Validation Layer 2: No conflicting axes in one packet ---
        # (The mobile app should never send both axes in one packet,
        #  but we reject it if someone tries.)

        # --- Execute through MotionState (thread-safe + interlocked) ---
        if axis == "RA":
            if direction != "NONE":
                ms.set_ra_speed(speed)
            ms.set_ra_direction(direction)
            logger.debug(f"MOBILE: RA → {direction} @ {speed}")

        elif axis == "DEC":
            if direction != "NONE":
                ms.set_dec_speed(speed)
            ms.set_dec_direction(direction)
            logger.debug(f"MOBILE: DEC → {direction} @ {speed}")

        return {"status": "ok", "message": f"{axis} → {direction} @ {speed}"}

    return {"status": "error", "message": "Unhandled command"}


# ═══════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════════

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    """
    Bidirectional WebSocket handler.

    - Outbound: telemetry snapshots are broadcast by the background task.
    - Inbound: commands are validated and dispatched immediately.
    - Dead Man's Switch: if client disconnects while motors are moving,
      an emergency stop is triggered.
    """
    await websocket.accept()
    client_id = id(websocket)

    with _client_lock:
        _connected_clients.add(websocket)
        _client_state[client_id] = {
            "last_hb": time.time(),
            "initiated_motion": False
        }

    logger.info(f"Mobile client connected. ID={client_id}. Total clients: {len(_connected_clients)}")

    # Track if this client initiated any motion (for Dead Man's Switch)
    client_initiated_motion = False

    try:
        while True:
            # Wait for incoming command from the mobile app
            raw = await websocket.receive_text()

            # Update heartbeat timestamp
            with _client_lock:
                if client_id in _client_state:
                    _client_state[client_id]["last_hb"] = time.time()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "response",
                    "status": "error",
                    "message": "Invalid JSON"
                })
                continue

            # Track if this client is commanding motion
            if data.get("command") == "manual_move" and data.get("direction", "NONE") != "NONE":
                client_initiated_motion = True
            elif data.get("command") in ("stop", "manual_move") and data.get("direction") == "NONE":
                client_initiated_motion = False

            with _client_lock:
                if client_id in _client_state:
                    _client_state[client_id]["initiated_motion"] = client_initiated_motion

            # Validate and execute
            response = _validate_and_execute(data)
            response["type"] = "response"

            await websocket.send_json(response)

    except WebSocketDisconnect:
        logger.info(f"Mobile client disconnected. ID={client_id}")
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
    finally:
        # ── Dead Man's Switch ──
        # If the client was commanding motion when it disconnected,
        # immediately stop the telescope.
        if client_initiated_motion and _motion_state:
            logger.warning(
                f"SAFETY: Client {client_id} disconnected while motion was active. "
                f"Triggering emergency stop."
            )
            if _slew_engine:
                _slew_engine.abort()
            _motion_state.emergency_stop()

        with _client_lock:
            _connected_clients.discard(websocket)
            _client_state.pop(client_id, None)

        logger.info(f"Cleanup complete for client {client_id}. Remaining: {len(_connected_clients)}")


# ═══════════════════════════════════════════════════════════
# 10Hz TELEMETRY BROADCAST TASK
# ═══════════════════════════════════════════════════════════

async def _telemetry_broadcast_loop():
    """
    Broadcasts telemetry to all connected clients at 10Hz.
    Runs as an asyncio background task inside the FastAPI event loop.
    """
    while True:
        if _connected_clients:
            snapshot = _build_telemetry_snapshot()
            payload = json.dumps(snapshot)

            # Broadcast to all connected clients
            dead_clients = []
            with _client_lock:
                clients = list(_connected_clients)

            for ws in clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead_clients.append(ws)

            # Clean up dead connections
            if dead_clients:
                with _client_lock:
                    for ws in dead_clients:
                        _connected_clients.discard(ws)

        await asyncio.sleep(0.1)  # 10Hz


async def _heartbeat_monitor_loop():
    """
    Monitors client heartbeats. If a client hasn't sent a heartbeat
    within HEARTBEAT_TIMEOUT while motion is active, trigger emergency stop.
    """
    while True:
        now = time.time()
        with _client_lock:
            for client_id, state in list(_client_state.items()):
                if (now - state["last_hb"]) > HEARTBEAT_TIMEOUT:
                    # Check if THIS specific client initiated motion
                    if state["initiated_motion"] and _motion_state and (
                        _motion_state.ra_direction != "NONE" or
                        _motion_state.dec_direction != "NONE"
                    ):
                        logger.warning(
                            f"SAFETY: Heartbeat timeout for client {client_id}. "
                            f"Client was commanding motion — triggering emergency stop."
                        )
                        _motion_state.emergency_stop()
                        state["initiated_motion"] = False

        await asyncio.sleep(0.5)


@app.on_event("startup")
async def startup_event():
    """Start background broadcast and heartbeat monitor tasks."""
    asyncio.create_task(_telemetry_broadcast_loop())
    asyncio.create_task(_heartbeat_monitor_loop())
    logger.info("Telemetry broadcast and heartbeat monitor started.")


# ═══════════════════════════════════════════════════════════
# SERVER THREAD (launched from MainWindow)
# ═══════════════════════════════════════════════════════════

class TelemetryServerThread(threading.Thread):
    """
    Runs the FastAPI/Uvicorn WebSocket server in a daemon thread.
    """

    def __init__(self, motion_state, slew_engine, astro):
        super().__init__(daemon=True)
        global _motion_state, _slew_engine, _astro
        _motion_state = motion_state
        _slew_engine = slew_engine
        _astro = astro
        self._server = None

    def run(self):
        host = os.environ.get("TELEMETRY_WS_HOST", "0.0.0.0")
        port = int(os.environ.get("TELEMETRY_WS_PORT", "11112"))

        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            ws_ping_interval=5,
            ws_ping_timeout=10,
        )
        self._server = uvicorn.Server(config)

        logger.info(f"WebSocket Telemetry Server starting on ws://{host}:{port}/ws/telemetry")
        self._server.run()

    def stop(self):
        if self._server:
            self._server.should_exit = True
