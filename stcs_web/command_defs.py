"""
Command definitions — shared validation constants for telescope commands.

These mirror the existing STCS V1 validation sets (telemetry_server.py).
Single source of truth for command validation across the web application.
"""

# Valid command types (mirrors telemetry_server.py VALID_COMMANDS)
# NOTE: "heartbeat" is intentionally excluded — it is an internal WS protocol
# command handled by control_client.py, not a user-facing web UI command.
VALID_COMMANDS = {
    "manual_move", "stop", "tracking_on", "tracking_off",
    "dome_cw", "dome_ccw", "dome_off",
    "slewtocoordinatesasync", "park", "emergency_stop",
    "synccalibration", "clear_offsets",
}

# Valid speeds for manual motion
VALID_SPEEDS = {"COARSE", "FINE_1", "FINE_2"}

# Valid directions per axis (matching STCS V1 MotionState)
VALID_DIRECTIONS = {
    "RA": {"EAST", "WEST", "NONE"},
    "DEC": {"NORTH", "SOUTH", "NONE"},
}

# Command categories for authorization
MANUAL_COMMANDS = {"manual_move", "stop"}
TRACKING_COMMANDS = {"tracking_on", "tracking_off"}
DOME_COMMANDS = {"dome_cw", "dome_ccw", "dome_off"}
SLEW_COMMANDS = {"slewtocoordinatesasync", "park"}
CALIBRATION_COMMANDS = {"synccalibration", "clear_offsets"}
EMERGENCY_COMMANDS = {"emergency_stop"}

ALL_COMMANDS = (
    MANUAL_COMMANDS | TRACKING_COMMANDS | DOME_COMMANDS |
    SLEW_COMMANDS | CALIBRATION_COMMANDS | EMERGENCY_COMMANDS
)