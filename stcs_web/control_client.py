"""
STCS WebSocket Command Client — Phase 3.

This module provides a WebSocket client that connects to the existing
STCS V1 WebSocket Telemetry Server (port 11112) to send validated
telescope commands through the existing safety/control layer.

WHY this exists:
  The browser must never speak hardware protocols directly. The existing
  STCS V1 WebSocket server already implements command validation,
  safety interlocks, and routes commands through MotionState/SlewEngine.
  This client reuses that exact path instead of creating a parallel one.

Protocol:
  - Connects to ws://127.0.0.1:11112/ws/telemetry
  - Sends JSON commands: {"command": "...", "axis": "...", "direction": "...", "speed": "..."}
  - Receives JSON responses: {"type": "response", "status": "ok|error", "message": "..."}
  - Heartbeat: {"command": "heartbeat"} -> {"type": "response", "status": "ok", "message": "pong"}

Commands supported (mirrors telemetry_server.py VALID_COMMANDS):
  - manual_move: axis (RA|DEC), direction (EAST|WEST|NONE|NORTH|SOUTH), speed (COARSE|FINE_1|FINE_2)
  - stop: emergency stop all motion
  - tracking_on: activate sidereal tracking
  - tracking_off: deactivate sidereal tracking
  - dome_cw: dome clockwise pulse
  - dome_ccw: dome counter-clockwise pulse
  - dome_off: dome stop pulse
  - heartbeat: keep-alive

Slew/Go-To commands are handled via Alpaca HTTP PUT (separate path).
"""

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

import websockets

logger = logging.getLogger("STCSControlClient")


class ConnectionState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


@dataclass
class CommandResult:
    """Result of a command sent to the STCS control layer."""
    accepted: bool
    executed: bool
    command: str
    message: str
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)


class STCSControlClient:
    """
    WebSocket client for sending commands to the STCS V1 telemetry server.
    
    Runs in a dedicated thread with its own asyncio event loop.
    Handles reconnection, command queueing, and response matching.
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11112,
        reconnect_interval: float = 3.0,
        connect_timeout: float = 5.0,
        command_timeout: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.url = f"ws://{host}:{port}/ws/telemetry"
        self.reconnect_interval = reconnect_interval
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        
        self._state = ConnectionState.DISCONNECTED
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        
        # Command/response matching
        self._pending: Dict[int, asyncio.Future] = {}
        self._cmd_counter = 0
        self._cmd_lock = threading.Lock()
        
        # Response callbacks
        self._response_callback: Optional[Callable[[CommandResult], None]] = None
        self._state_change_callback: Optional[Callable[[ConnectionState], None]] = None
        
        # Heartbeat
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_interval = 2.0  # seconds
        
        # Statistics
        self._stats = {
            "commands_sent": 0,
            "commands_accepted": 0,
            "commands_rejected": 0,
            "commands_timed_out": 0,
            "reconnects": 0,
            "last_command_time": 0.0,
            "last_response_time": 0.0,
        }
        self._stats_lock = threading.Lock()
    
    @property
    def state(self) -> ConnectionState:
        return self._state
    
    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._ws is not None
    
    def set_response_callback(self, callback: Callable[[CommandResult], None]):
        """Set callback for command responses."""
        self._response_callback = callback
    
    def set_state_change_callback(self, callback: Callable[[ConnectionState], None]):
        """Set callback for connection state changes."""
        self._state_change_callback = callback
    
    def _set_state(self, new_state: ConnectionState):
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            logger.info(f"Control client state: {old_state.value} -> {new_state.value}")
            if self._state_change_callback:
                try:
                    self._state_change_callback(new_state)
                except Exception:
                    logger.exception("State change callback failed")
    
    def start(self):
        """Start the client in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("STCS Control Client thread started")
    
    def stop(self):
        """Stop the client."""
        self._stop_event.set()
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("STCS Control Client stopped")
    
    def _run_loop(self):
        """Run the asyncio event loop in this thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._client_main())
        finally:
            self._loop.close()
            self._loop = None
    
    async def _client_main(self):
        """Main async client loop with reconnection."""
        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Control client error: {e}")
                self._set_state(ConnectionState.FAILED)
            
            if self._stop_event.is_set():
                break
            
            self._set_state(ConnectionState.RECONNECTING)
            with self._stats_lock:
                self._stats["reconnects"] += 1
            await asyncio.sleep(self.reconnect_interval)
    
    async def _connect_and_run(self):
        """Connect and run the message handler."""
        self._set_state(ConnectionState.CONNECTING)
        
        try:
            async with websockets.connect(
                self.url,
                open_timeout=self.connect_timeout,
                ping_interval=10,
                ping_timeout=5,
            ) as ws:
                self._ws = ws
                self._set_state(ConnectionState.CONNECTED)
                self._connected_event.set()
                logger.info(f"Connected to STCS control server at {self.url}")
                
                # Start heartbeat
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                # Handle incoming messages
                async for message in ws:
                    if self._stop_event.is_set():
                        break
                    await self._handle_message(message)
        
        except asyncio.CancelledError:
            raise
        except (ConnectionRefusedError, OSError) as e:
            # Expected when STCS V1 server is not running - don't spam logs
            logger.debug(f"STCS control server not available: {e}")
            self._set_state(ConnectionState.DISCONNECTED)
            self._connected_event.clear()
        except Exception as e:
            logger.warning(f"Control connection error: {e}")
            self._set_state(ConnectionState.DISCONNECTED)
            self._connected_event.clear()
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            self._ws = None
            self._connected_event.clear()
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to keep connection alive."""
        while not self._stop_event.is_set():
            try:
                await self._send_raw({"command": "heartbeat"}, wait_response=False)
                await asyncio.sleep(self._heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                break
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        
        msg_type = data.get("type")
        
        if msg_type == "response":
            # Match response to pending command
            cmd_id = data.get("command_id")
            if cmd_id is not None:
                with self._cmd_lock:
                    future = self._pending.pop(cmd_id, None)
                if future and not future.done():
                    result = CommandResult(
                        accepted=data.get("status") == "ok",
                        executed=data.get("executed", False),
                        command=data.get("command", "unknown"),
                        message=data.get("message", ""),
                        reason=data.get("reason", ""),
                        details=data,
                    )
                    future.set_result(result)
                    
                    with self._stats_lock:
                        self._stats["last_response_time"] = time.time()
                        if result.accepted:
                            self._stats["commands_accepted"] += 1
                        else:
                            self._stats["commands_rejected"] += 1
                    
                    if self._response_callback:
                        try:
                            self._response_callback(result)
                        except Exception:
                            logger.exception("Response callback failed")
        
        elif msg_type == "telemetry":
            # Telemetry broadcasts are ignored here (separate telemetry module handles them)
            pass
    
    def _next_cmd_id(self) -> int:
        with self._cmd_lock:
            self._cmd_counter += 1
            return self._cmd_counter
    
    async def _send_raw(self, data: Dict[str, Any], wait_response: bool = True) -> Optional[CommandResult]:
        """Send raw JSON command. Returns CommandResult if wait_response=True."""
        if not self.is_connected or not self._ws:
            return CommandResult(
                accepted=False,
                executed=False,
                command=data.get("command", "unknown"),
                message="Not connected to STCS control server",
                reason="DISCONNECTED",
            )
        
        cmd_id = self._next_cmd_id() if wait_response else 0
        payload = dict(data)
        if wait_response:
            payload["command_id"] = cmd_id
        
        future: Optional[asyncio.Future] = None
        if wait_response:
            future = self._loop.create_future()
            with self._cmd_lock:
                self._pending[cmd_id] = future
        
        try:
            await self._ws.send(json.dumps(payload))
            with self._stats_lock:
                self._stats["commands_sent"] += 1
                self._stats["last_command_time"] = time.time()
        except Exception as e:
            if future:
                with self._cmd_lock:
                    self._pending.pop(cmd_id, None)
                future.set_exception(e)
            raise
        
        if wait_response and future:
            try:
                return await asyncio.wait_for(future, timeout=self.command_timeout)
            except asyncio.TimeoutError:
                with self._cmd_lock:
                    self._pending.pop(cmd_id, None)
                with self._stats_lock:
                    self._stats["commands_timed_out"] += 1
                return CommandResult(
                    accepted=False,
                    executed=False,
                    command=data.get("command", "unknown"),
                    message="Command timed out",
                    reason="TIMEOUT",
                )
        
        return None
    
    def send_command(self, command: str, **fields) -> CommandResult:
        """
        Send a command synchronously (blocks until response or timeout).
        
        Args:
            command: Command name (manual_move, stop, tracking_on, etc.)
            **fields: Command-specific fields
            
        Returns:
            CommandResult with accepted/executed status
        """
        if not self._loop:
            return CommandResult(
                accepted=False,
                executed=False,
                command=command,
                message="Client not started",
                reason="NOT_STARTED",
            )
        
        data = {"command": command}
        data.update(fields)
        
        future = asyncio.run_coroutine_threadsafe(
            self._send_raw(data, wait_response=True),
            self._loop
        )
        try:
            return future.result(timeout=self.command_timeout + 1.0)
        except Exception as e:
            return CommandResult(
                accepted=False,
                executed=False,
                command=command,
                message=f"Send failed: {e}",
                reason="SEND_FAILED",
            )
    
    def send_command_async(self, command: str, callback: Callable[[CommandResult], None], **fields):
        """
        Send a command asynchronously with callback.
        
        Args:
            command: Command name
            callback: Called with CommandResult when response received
            **fields: Command-specific fields
        """
        if not self._loop:
            callback(CommandResult(
                accepted=False, executed=False, command=command,
                message="Client not started", reason="NOT_STARTED"
            ))
            return
        
        data = {"command": command}
        data.update(fields)
        
        async def _send():
            result = await self._send_raw(data, wait_response=True)
            callback(result)
        
        asyncio.run_coroutine_threadsafe(_send(), self._loop)
    
    def wait_connected(self, timeout: float = 10.0) -> bool:
        """Wait for connection to be established."""
        return self._connected_event.wait(timeout)
    
    def get_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return dict(self._stats)
    
    # ─── Convenience Command Methods ───
    
    def manual_move(self, axis: str, direction: str, speed: str) -> CommandResult:
        """Send manual move command."""
        return self.send_command("manual_move", axis=axis, direction=direction, speed=speed)
    
    def stop(self) -> CommandResult:
        """Send emergency stop."""
        return self.send_command("stop")
    
    def tracking_on(self) -> CommandResult:
        """Activate tracking."""
        return self.send_command("tracking_on")
    
    def tracking_off(self) -> CommandResult:
        """Deactivate tracking."""
        return self.send_command("tracking_off")
    
    def dome_cw(self) -> CommandResult:
        """Dome clockwise pulse."""
        return self.send_command("dome_cw")
    
    def dome_ccw(self) -> CommandResult:
        """Dome counter-clockwise pulse."""
        return self.send_command("dome_ccw")
    
    def dome_off(self) -> CommandResult:
        """Dome stop pulse."""
        return self.send_command("dome_off")
    
    def heartbeat(self) -> CommandResult:
        """Send heartbeat."""
        return self.send_command("heartbeat")


# Module-level singleton
_control_client: Optional[STCSControlClient] = None


def get_control_client() -> STCSControlClient:
    """Get or create the global control client."""
    global _control_client
    if _control_client is None:
        host = os.environ.get("TELEMETRY_WS_HOST", "127.0.0.1")
        port = int(os.environ.get("TELEMETRY_WS_PORT", "11112"))
        _control_client = STCSControlClient(host=host, port=port)
    return _control_client


def start_control_client() -> STCSControlClient:
    """Start the global control client."""
    client = get_control_client()
    client.start()
    return client


def stop_control_client():
    """Stop the global control client."""
    global _control_client
    if _control_client:
        _control_client.stop()
        _control_client = None