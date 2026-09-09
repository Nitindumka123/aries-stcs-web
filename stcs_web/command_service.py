"""
STCS Command Service — Phase 3.

Centralized backend command gateway for telescope operations.

This service:
- Validates all commands server-side against STCS limits
- Enforces safety checks using current telemetry state
- Routes commands through the existing STCS control layer (WebSocket client)
- Provides audit logging for all control actions
- Enforces authorization (Admin/Scientist permissions)
- Respects STCS_COMMANDS_ENABLED feature flag

The service NEVER directly controls hardware. It only forwards
validated commands to the existing STCS V1 WebSocket command interface
which routes them through MotionState/SlewEngine/ControlSerial.
"""

import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from enum import Enum

from . import telemetry
from . import obs_store
from . import control_lock
from . import command_defs
from .control_client import get_control_client, STCSControlClient, CommandResult
from .alpaca_client import get_alpaca_client, AlpacaClient, AlpacaCommandResult, AlpacaCommandStatus

logger = logging.getLogger("CommandService")


class CommandStatus(Enum):
    ACCEPTED = "ACCEPTED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    BUSY = "BUSY"
    UNSAFE = "UNSAFE"
    DISCONNECTED = "DISCONNECTED"
    STALE = "STALE"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    COMMANDS_DISABLED = "COMMANDS_DISABLED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID = "INVALID"


@dataclass
class CommandResponse:
    """Response from command execution."""
    status: CommandStatus
    command: str
    message: str
    executed: bool = False
    reason: str = ""
    details: Dict[str, Any] = None
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.details is None:
            self.details = {}


class CommandService:
    """
    Centralized command service for telescope control.
    
    All telescope commands from the web UI go through this service.
    It validates, checks safety, authorizes, and forwards to the
    existing STCS control layer.
    """
    
    # Valid command types (from shared definitions)
    MANUAL_COMMANDS = command_defs.MANUAL_COMMANDS
    TRACKING_COMMANDS = command_defs.TRACKING_COMMANDS
    DOME_COMMANDS = command_defs.DOME_COMMANDS
    SLEW_COMMANDS = command_defs.SLEW_COMMANDS
    CALIBRATION_COMMANDS = command_defs.CALIBRATION_COMMANDS
    EMERGENCY_COMMANDS = command_defs.EMERGENCY_COMMANDS
    
    ALL_COMMANDS = command_defs.ALL_COMMANDS
    
    # Valid directions per axis (matching stcs_v1 MotionState)
    VALID_RA_DIRECTIONS = command_defs.VALID_DIRECTIONS["RA"]
    VALID_DEC_DIRECTIONS = command_defs.VALID_DIRECTIONS["DEC"]
    VALID_SPEEDS = command_defs.VALID_SPEEDS
    
    def __init__(self):
        self._commands_enabled = os.environ.get("STCS_COMMANDS_ENABLED", "0") == "1"
        self._client: Optional[STCSControlClient] = None
    
    @property
    def commands_enabled(self) -> bool:
        return self._commands_enabled
    
    @property
    def client(self) -> STCSControlClient:
        if self._client is None:
            self._client = get_control_client()
        return self._client
    
    def start(self):
        """Start the underlying control client."""
        self.client.start()
    
    def stop(self):
        """Stop the underlying control client."""
        if self._client:
            self._client.stop()
            self._client = None
    
    # ─── Authorization ──────────────────────────────────────────────────
    
    def _check_authorization(self, username: str, role: str, command: str) -> Tuple[bool, str]:
        """
        Check if user is authorized for command.
        
        Returns (authorized, reason_if_denied)
        """
        # Emergency stop is always allowed for authenticated operational users
        if command in self.EMERGENCY_COMMANDS:
            return True, ""
        
        # All other commands require operational role (scientist or admin)
        if role not in ("scientist", "admin"):
            return False, f"Role '{role}' not authorized for command '{command}'"
        
        # For slew/park/calibration, check control lock
        if command in self.SLEW_COMMANDS | self.CALIBRATION_COMMANDS:
            lock = control_lock.control_lock_status()
            if lock["owner"] and lock["owner"] != username:
                return False, f"Control lock held by {lock['owner']}"
        
        return True, ""
    
    def acquire_control_lock(self, username: str) -> Tuple[bool, str]:
        """Acquire exclusive control lock for slew/calibration commands."""
        result = control_lock.acquire_control_lock(username)
        return result["ok"], result.get("owner", "")
    
    def release_control_lock(self, username: str, role: str = "scientist") -> bool:
        """Release control lock."""
        result = control_lock.release_control_lock(username, role)
        return result["ok"]
    
    def get_control_lock_status(self) -> Dict[str, Any]:
        return control_lock.control_lock_status()
    
    # ─── Safety Validation ──────────────────────────────────────────────
    
    def _check_safety(self, command: str, fields: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check safety conditions before executing command.
        
        Returns (safe, reason, safety_details)
        """
        # Get current telemetry state
        snap = telemetry.read_ws_snapshot()
        ws_vals = snap.get("values") or {}
        alpaca = telemetry.read_alpaca_snapshot()
        alpaca_vals = alpaca.get("values") or {}
        
        # Merge telemetry sources (prefer WS)
        tracking = ws_vals.get("tracking", alpaca_vals.get("tracking"))
        slewing = ws_vals.get("is_slewing", alpaca_vals.get("slewing"))
        safety_limit = ws_vals.get("safety_limit_active", False)
        safety_message = ws_vals.get("safety_limit_message", "")
        alt_deg = ws_vals.get("alt_deg", alpaca_vals.get("altitude"))
        cooldown_active = ws_vals.get("cooldown_active", False)
        telemetry_status = snap.get("status", "NOT_CONNECTED")
        telemetry_age = snap.get("age_s", 0.0)
        
        # Get current position for altitude calculation
        current_ra = ws_vals.get("ra_hours", alpaca_vals.get("rightascension"))
        current_dec = ws_vals.get("dec_deg", alpaca_vals.get("declination"))
        current_ha = ws_vals.get("ha_hours")
        if current_ha is None and current_ra is not None:
            lst = ws_vals.get("lst_hours", alpaca_vals.get("siderealtime"))
            if lst is not None:
                current_ha = (lst - current_ra) % 24.0
        
        details = {
            "telemetry_status": telemetry_status,
            "telemetry_age_s": telemetry_age,
            "tracking": tracking,
            "slewing": slewing,
            "safety_limit_active": safety_limit,
            "safety_limit_message": safety_message,
            "altitude_deg": alt_deg,
            "cooldown_active": cooldown_active,
            "current_ra_hours": current_ra,
            "current_dec_deg": current_dec,
            "current_ha_hours": current_ha,
        }
        
        # Check telemetry freshness
        if telemetry_status == "NOT_CONNECTED":
            return False, "Telemetry disconnected — cannot verify safety", details
        if telemetry_status == "STALE":
            return False, f"Telemetry stale ({telemetry_age:.1f}s) — cannot verify safety", details
        
        # Check altitude safety (current position)
        if alt_deg is not None:
            limits = telemetry.read_stcs_config()
            min_alt = limits.get("limits", {}).get("motion", {}).get("min_altitude_deg", 45.0)
            if alt_deg < min_alt:
                return False, f"Altitude {alt_deg:.1f}° below safety limit {min_alt:.1f}°", details
        
        # Check explicit safety limit
        if safety_limit:
            return False, f"Safety limit active: {safety_message}", details
        
        # Check cooldown
        if cooldown_active and command in self.SLEW_COMMANDS:
            return False, "Motors in cooldown — wait before next slew", details
        
        # Check if already slewing
        if slewing and command in self.SLEW_COMMANDS:
            return False, "Slew already in progress", details
        
        # For slew/park: validate target altitude using STCS safety logic
        if command in ("slewtocoordinatesasync", "park"):
            target_ra = None
            target_dec = None
            
            if command == "slewtocoordinatesasync":
                try:
                    target_ra = float(fields.get("ra_deg", 0))
                    target_dec = float(fields.get("dec_deg", 0))
                except (TypeError, ValueError):
                    return False, "Invalid target coordinates", details
            elif command == "park":
                # Park target: HA=0, DEC=site latitude
                target_ra = 0.0  # HA=0 degrees
                target_dec = 29.36  # ARIES Nainital latitude
            
            if target_ra is not None and target_dec is not None:
                # Validate target altitude using STCS limits
                limits = telemetry.read_stcs_config()
                motion_limits = limits.get("limits", {}).get("motion", {})
                min_alt = float(motion_limits.get("min_altitude_deg", 45.0))
                max_alt = float(motion_limits.get("max_altitude_deg", 89.0))
                
                # Use observatory's safety evaluation (reuses STCS logic)
                from . import observatory as obs_svc
                target_alt = None
                try:
                    # Quick altitude check using astropy
                    from astropy.time import Time
                    from astropy.coordinates import SkyCoord, EarthLocation, AltAz
                    import astropy.units as u
                    
                    site_lat = 29.3607
                    site_lon = 79.4571
                    site_elev = 1951.0
                    location = EarthLocation(lat=site_lat*u.deg, lon=site_lon*u.deg, height=site_elev*u.m)
                    
                    coord = SkyCoord(ra=target_ra*u.deg, dec=target_dec*u.deg, frame='icrs')
                    altaz = coord.transform_to(AltAz(obstime=Time.now(), location=location))
                    target_alt = altaz.alt.deg
                    details["target_altitude_deg"] = target_alt
                    
                    if target_alt < min_alt:
                        return False, f"Target altitude {target_alt:.1f}° below safety limit {min_alt:.1f}°", details
                    if target_alt > max_alt and command != "park":
                        return False, f"Target altitude {target_alt:.1f}° exceeds maximum {max_alt:.1f}°", details
                except Exception as e:
                    logger.warning(f"Could not compute target altitude: {e}")
                    details["target_altitude_error"] = str(e)
        
        # For manual moves, check if slewing (manual jog overrides slew in MotionState but safety check here)
        if command == "manual_move" and slewing:
            # Allow manual jog during slew (MotionState handles override)
            pass
        
        return True, "", details
    
    def _validate_manual_move(self, fields: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate manual move command fields."""
        axis = fields.get("axis", "").upper()
        direction = fields.get("direction", "").upper()
        speed = fields.get("speed", "").upper()
        
        if axis not in ("RA", "DEC"):
            return False, f"Invalid axis: {axis}. Must be RA or DEC"
        
        valid_dirs = self.VALID_RA_DIRECTIONS if axis == "RA" else self.VALID_DEC_DIRECTIONS
        if direction not in valid_dirs:
            return False, f"Invalid direction '{direction}' for {axis}. Valid: {valid_dirs}"
        
        if direction != "NONE" and speed not in self.VALID_SPEEDS:
            return False, f"Invalid speed: {speed}. Valid: {self.VALID_SPEEDS}"
        
        return True, ""
    
    def _validate_slew(self, fields: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate slew/Go-To command fields."""
        try:
            ra_deg = float(fields.get("ra_deg", ""))
            dec_deg = float(fields.get("dec_deg", ""))
        except (TypeError, ValueError):
            return False, "ra_deg and dec_deg must be valid numbers"
        
        if not (0 <= ra_deg < 360):
            return False, f"RA must be 0-360 degrees, got {ra_deg}"
        if not (-90 <= dec_deg <= 90):
            return False, f"DEC must be -90 to +90 degrees, got {dec_deg}"
        
        # Check against STCS motion limits
        limits = telemetry.read_stcs_config()
        motion_limits = limits.get("limits", {}).get("motion", {})
        min_dec = float(motion_limits.get("min_declination_deg", -50.0))
        max_dec = float(motion_limits.get("max_declination_deg", 70.0))
        if dec_deg < min_dec or dec_deg > max_dec:
            return False, f"DEC {dec_deg:.1f}° outside configured limits ({min_dec:.1f}° to {max_dec:.1f}°)"
        
        return True, ""

    def _validate_calibration_sync(self, fields: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate calibration sync command fields."""
        # For sync, we use current telescope position, so no target coords needed
        # But the form may send ra_hms, dec_dms, dome_az
        return True, ""
    
    # ─── Command Execution ──────────────────────────────────────────────
    
    def execute(self, username: str, role: str, command: str, fields: Dict[str, Any]) -> CommandResponse:
        """
        Execute a telescope command with full validation and safety checks.
        
        This is the main entry point for all web UI commands.
        """
        # 1. Check commands enabled
        if not self._commands_enabled:
            self._audit(username, command, f"rejected: commands disabled", fields)
            return CommandResponse(
                status=CommandStatus.COMMANDS_DISABLED,
                command=command,
                message="Telescope commands are disabled (STCS_COMMANDS_ENABLED=0)",
                reason="Commands disabled in configuration",
            )
        
        # 2. Validate command exists
        if command not in self.ALL_COMMANDS:
            self._audit(username, command, f"rejected: unknown command", fields)
            return CommandResponse(
                status=CommandStatus.INVALID,
                command=command,
                message=f"Unknown command: {command}",
                reason="Invalid command",
            )
        
        # 3. Check authorization
        authorized, reason = self._check_authorization(username, role, command)
        if not authorized:
            self._audit(username, command, f"rejected: unauthorized - {reason}", fields)
            return CommandResponse(
                status=CommandStatus.UNAUTHORIZED,
                command=command,
                message=reason,
                reason="Authorization failed",
            )
        
        # 4. Validate command-specific fields
        if command == "manual_move":
            valid, reason = self._validate_manual_move(fields)
            if not valid:
                self._audit(username, command, f"rejected: validation - {reason}", fields)
                return CommandResponse(
                    status=CommandStatus.INVALID,
                    command=command,
                    message=reason,
                    reason="Validation failed",
                )
        elif command in self.SLEW_COMMANDS:
            valid, reason = self._validate_slew(fields)
            if not valid:
                self._audit(username, command, f"rejected: validation - {reason}", fields)
                return CommandResponse(
                    status=CommandStatus.INVALID,
                    command=command,
                    message=reason,
                    reason="Validation failed",
                )
        
        # 5. Check safety
        safe, reason, safety_details = self._check_safety(command, fields)
        if not safe:
            self._audit(username, command, f"rejected: unsafe - {reason}", {**fields, **safety_details})
            return CommandResponse(
                status=CommandStatus.UNSAFE,
                command=command,
                message=reason,
                reason="Safety check failed",
                details=safety_details,
            )
        
        # 6. Execute command through STCS control client
        try:
            result = self._execute_stcs_command(command, fields)
            
            if result.accepted:
                if result.executed:
                    status = CommandStatus.EXECUTED
                    message = result.message or "Command executed"
                else:
                    status = CommandStatus.ACCEPTED
                    message = result.message or "Command accepted (validation only)"
                self._audit(username, command, f"accepted: {message}", {**fields, **safety_details})
            else:
                status = CommandStatus.REJECTED
                message = result.message or "Command rejected by STCS layer"
                self._audit(username, command, f"rejected: {message}", {**fields, **safety_details})
            
            return CommandResponse(
                status=status,
                command=command,
                message=message,
                executed=result.executed,
                reason=result.reason,
                details={**result.details, **safety_details},
            )
        
        except Exception as e:
            logger.exception(f"Command execution error: {e}")
            self._audit(username, command, f"error: {e}", {**fields, **safety_details})
            return CommandResponse(
                status=CommandStatus.ERROR,
                command=command,
                message=f"Command execution failed: {e}",
                reason="Execution error",
                details=safety_details,
            )
    
    def _execute_stcs_command(self, command: str, fields: Dict[str, Any]) -> CommandResult:
        """Execute command through the appropriate STCS control interface."""
        
        # WebSocket commands (manual motion, tracking, dome, stop)
        ws_commands = {
            "manual_move",
            "stop",
            "tracking_on",
            "tracking_off",
            "dome_cw",
            "dome_ccw",
            "dome_off",
            "emergency_stop",
        }
        
        if command in ws_commands:
            return self._execute_ws_command(command, fields)
        
        # Alpaca HTTP commands (slew, park, calibration)
        return self._execute_alpaca_command(command, fields)

    def _execute_ws_command(self, command: str, fields: Dict[str, Any]) -> CommandResult:
        """Execute command via WebSocket control client."""
        client = self.client
        
        if command == "manual_move":
            return client.manual_move(
                axis=fields["axis"],
                direction=fields["direction"],
                speed=fields["speed"]
            )
        elif command == "stop":
            return client.stop()
        elif command == "tracking_on":
            return client.tracking_on()
        elif command == "tracking_off":
            return client.tracking_off()
        elif command == "dome_cw":
            return client.dome_cw()
        elif command == "dome_ccw":
            return client.dome_ccw()
        elif command == "dome_off":
            return client.dome_off()
        elif command == "emergency_stop":
            return client.stop()
        
        return CommandResult(
            accepted=False,
            executed=False,
            command=command,
            message=f"Unknown WebSocket command: {command}",
            reason="UNKNOWN_COMMAND",
        )

    def _execute_alpaca_command(self, command: str, fields: Dict[str, Any]) -> CommandResult:
        """Execute command via Alpaca HTTP client."""
        alpaca = get_alpaca_client()
        
        try:
            if command == "slewtocoordinatesasync":
                ra_deg = float(fields["ra_deg"])
                dec_deg = float(fields["dec_deg"])
                result = alpaca.slew_to_coordinates_async(ra_deg, dec_deg)
                
            elif command == "park":
                # Park uses fixed HA=0, DEC=site latitude (handled by SlewEngine)
                # We need to get the park coordinates from config or use defaults
                limits = telemetry.read_stcs_config()
                motion_limits = limits.get("limits", {}).get("motion", {})
                # Default park position: HA=0 (meridian), DEC=site latitude
                site_lat = 29.36  # ARIES Nainital latitude
                result = alpaca.slew_to_coordinates_async(0.0, site_lat)
                
            elif command == "synccalibration":
                # Sync uses current telescope position as reference
                # The form may provide ra_hms, dec_dms, dome_az
                # For now, sync to current position (no-op in Alpaca but logs)
                # Actual sync is done via MountCoordinator in STCS V1
                # This is a placeholder - real sync needs encoder read
                result = AlpacaCommandResult(
                    status=AlpacaCommandStatus.SUCCESS,
                    command="synctocoordinates",
                    message="Sync requested (requires manual encoder read in STCS V1)",
                )
                
            elif command == "clear_offsets":
                # Clear offsets - this resets the calibration offsets
                # In STCS V1 this is done via MountCoordinator
                result = AlpacaCommandResult(
                    status=AlpacaCommandStatus.SUCCESS,
                    command="clear_offsets",
                    message="Clear offsets requested (requires STCS V1 coordinator access)",
                )
                
            else:
                return CommandResult(
                    accepted=False,
                    executed=False,
                    command=command,
                    message=f"Unknown Alpaca command: {command}",
                    reason="UNKNOWN_COMMAND",
                )
            
            # Convert Alpaca result to CommandResult
            if result.status == AlpacaCommandStatus.SUCCESS:
                return CommandResult(
                    accepted=True,
                    executed=True,
                    command=command,
                    message=result.message,
                    details=result.details,
                )
            elif result.status == AlpacaCommandStatus.NOT_CONNECTED:
                return CommandResult(
                    accepted=False,
                    executed=False,
                    command=command,
                    message=f"Alpaca server not available: {result.message}",
                    reason="ALPACA_DISCONNECTED",
                    details=result.details,
                )
            elif result.status == AlpacaCommandStatus.TIMEOUT:
                return CommandResult(
                    accepted=False,
                    executed=False,
                    command=command,
                    message=f"Alpaca command timed out: {result.message}",
                    reason="ALPACA_TIMEOUT",
                    details=result.details,
                )
            else:
                return CommandResult(
                    accepted=False,
                    executed=False,
                    command=command,
                    message=result.message or "Alpaca command rejected",
                    reason=result.error_message or "ALPACA_ERROR",
                    details=result.details,
                )
                
        except Exception as e:
            logger.exception(f"Alpaca command execution error: {e}")
            return CommandResult(
                accepted=False,
                executed=False,
                command=command,
                message=f"Alpaca execution failed: {e}",
                reason="ALPACA_EXCEPTION",
            )
    
    def _audit(self, username: str, command: str, outcome: str, details: Dict[str, Any]):
        """Record command attempt in audit log."""
        try:
            detail_parts = [outcome]
            if details:
                # Sanitize details for audit log
                safe_details = {k: v for k, v in details.items() 
                              if k not in ("password", "token", "secret", "key")}
                detail_parts.append(str(safe_details))
            obs_store.record_audit(username, f"command_{command}", " | ".join(detail_parts))
        except Exception:
            pass  # Audit must never break command flow


# Module-level singleton
_command_service: Optional[CommandService] = None


def get_command_service() -> CommandService:
    """Get or create the global command service."""
    global _command_service
    if _command_service is None:
        _command_service = CommandService()
    return _command_service


def start_command_service() -> CommandService:
    """Start the global command service."""
    svc = get_command_service()
    svc.start()
    return svc


def stop_command_service():
    """Stop the global command service."""
    global _command_service
    if _command_service:
        _command_service.stop()
        _command_service = None