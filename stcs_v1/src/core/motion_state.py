# src/core/motion_state.py
"""
Central Thread-Safe Motion State Manager.

Tracks all telescope motion state: RA/DEC speed & direction, dome,
tracking, and simulation position. Enforces safety interlocks
(no opposing directions simultaneously). Produces the 7-byte relay
payload for the DUO Mega 2560 controller.

Relay signals fall into two categories:
- HELD signals (RA/DEC motions): stay HIGH as long as button is held
- PULSE signals (Dome CW/CCW/OFF): go HIGH for one send cycle.
- Track ON/OFF pulses are held for 20 send cycles to match the legacy
  controller timing.
"""
import os
import threading
import logging

logger = logging.getLogger("MotionState")

TRACK_PULSE_TICKS = 20

# Motion speeds in degrees per second (from telescope_control_gui.py)
SPEEDS = {
    'COARSE': 2.0,
    'FINE_1': 0.05,
    'FINE_2': 0.002777,
    'TRACK': 0.004178074  # True Sidereal Rate
}

# Slew error thresholds (degrees)
# IMPORTANT: Each threshold must be >= the slip_deg of its own tier to prevent
# hunting (infinite coast→recheck→coast cycles). See slip_calibration defaults
# in slew_engine.py: COARSE slip=0.5°, FINE_1 slip=0.05°, FINE_2 slip=0.005°.
#
# Motor run time estimates (with slip early-cutoff):
#   COARSE: unlimited (fast motor, low risk)
#   FINE_1: effective zone 0.5° → 0.0166° (slip cutoff)
#   FINE_2: effective zone 0.0166° → 0.003° (slip cutoff)
THRESH_COARSE = 0.5      # °  — COARSE → FINE_1 (reduced from 1.0 to halve FINE_1 time)
THRESH_FINE1  = 0.016667 # °  — FINE_1 → FINE_2 (1 arcminute, to protect FINE_2 motor)
TOLERANCE     = 0.003    # °  — Arrived (relaxed from 0.001° to reduce FINE_2 re-trigger)


class MotionState:
    """
    Thread-safe telescope motion state with safety interlocks.
    
    All state mutations go through setter methods that enforce
    mutual exclusion of opposing directions.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Operating mode from .env
        self.mode = os.environ.get("TELESCOPE_MODE", "SIMULATION").upper()

        # --- RA Axis ---
        self.ra_speed = "COARSE"       # Current RA speed selection
        self.ra_direction = "NONE"     # EAST / WEST / NONE (held signal)

        # --- DEC Axis ---
        self.dec_speed = "COARSE"      # Current DEC speed selection
        self.dec_direction = "NONE"    # NORTH / SOUTH / NONE (held signal)

        # --- Tracking (pulse signals) ---
        self.tracking_active = False   # GUI state: is tracking logically ON?
        self._pulse_track_on_ticks = 0
        self._pulse_track_off_ticks = 0

        # --- Dome (pulse signals) ---
        self.dome_state = "OFF"        # GUI state: CW / CCW / OFF
        self._pulse_dome_cw = False
        self._pulse_dome_ccw = False
        self._pulse_dome_off = False

        # --- Simulation / Telemetry Position ---
        self.sim_ha_deg = 0.0          # Simulated Hour Angle (degrees)
        self.sim_dec_deg = 29.36       # Simulated Declination (site latitude)
        self.dome_az_deg = 0.0         # Dome Azimuth (degrees)
        self.telescope_position_valid = True
        self.telescope_position_error = ""
        self.safety_limit_active = False
        self.safety_limit_message = ""
        self.weather_data = None       # Dictionary from weather_worker

        # --- Slew State ---
        self.is_slewing = False
        self.slew_ra_speed = None      # Speed selected by auto-slew engine
        self.slew_ra_dir = 0           # +1 / -1 / 0
        self.slew_dec_speed = None
        self.slew_dec_dir = 0

        # --- Cooldown ---
        self.cooldown_active = False
        self.request_cooldown = False

        logger.info(f"MotionState initialized. Mode={self.mode}")

    # ─── RA SPEED SELECTION ─────────────────────────────────────
    def set_ra_speed(self, speed: str):
        """Set RA speed: COARSE, FINE_1, or FINE_2"""
        assert speed in ("COARSE", "FINE_1", "FINE_2")
        with self._lock:
            self.ra_speed = speed

    # ─── DEC SPEED SELECTION ────────────────────────────────────
    def set_dec_speed(self, speed: str):
        """Set DEC speed: COARSE, FINE_1, or FINE_2"""
        assert speed in ("COARSE", "FINE_1", "FINE_2")
        with self._lock:
            self.dec_speed = speed

    # ─── RA DIRECTION (HELD SIGNAL) ────────────────────────────
    def set_ra_direction(self, direction: str):
        """
        Set RA direction with safety interlock.
        Setting EAST clears WEST and vice versa.
        """
        assert direction in ("EAST", "WEST", "NONE")
        with self._lock:
            self.ra_direction = direction

    # ─── DEC DIRECTION (HELD SIGNAL) ───────────────────────────
    def set_dec_direction(self, direction: str):
        """
        Set DEC direction with safety interlock.
        Setting NORTH clears SOUTH and vice versa.
        """
        assert direction in ("NORTH", "SOUTH", "NONE")
        with self._lock:
            self.dec_direction = direction

    # ─── TRACKING (PULSE SIGNALS) ──────────────────────────────
    def activate_tracking(self):
        """Queue a legacy-duration pulse to turn tracking ON."""
        with self._lock:
            self.tracking_active = True
            self._pulse_track_on_ticks = TRACK_PULSE_TICKS
            self._pulse_track_off_ticks = 0

    def deactivate_tracking(self):
        """Queue a legacy-duration pulse to turn tracking OFF."""
        with self._lock:
            self.tracking_active = False
            self._pulse_track_off_ticks = TRACK_PULSE_TICKS
            self._pulse_track_on_ticks = 0

    # ─── DOME (PULSE SIGNALS) ──────────────────────────────────
    def set_dome_cw(self):
        """Queue a one-shot pulse for Dome CW. Cancels CCW."""
        with self._lock:
            self.dome_state = "CW"
            self._pulse_dome_cw = True
            self._pulse_dome_ccw = False
            self._pulse_dome_off = False

    def set_dome_ccw(self):
        """Queue a one-shot pulse for Dome CCW. Cancels CW."""
        with self._lock:
            self.dome_state = "CCW"
            self._pulse_dome_ccw = True
            self._pulse_dome_cw = False
            self._pulse_dome_off = False

    def set_dome_off(self):
        """Queue a one-shot pulse for Dome OFF."""
        with self._lock:
            self.dome_state = "OFF"
            self._pulse_dome_off = True
            self._pulse_dome_cw = False
            self._pulse_dome_ccw = False

    # ─── EMERGENCY STOP ────────────────────────────────────────
    def emergency_stop(self):
        """Clear ALL motion immediately."""
        with self._lock:
            self.ra_direction = "NONE"
            self.dec_direction = "NONE"
            self.is_slewing = False
            self.slew_ra_speed = None
            self.slew_ra_dir = 0
            self.slew_dec_speed = None
            self.slew_dec_dir = 0
            # Don't change tracking state; user manages that separately
            logger.warning("EMERGENCY STOP: All motion cleared.")

    def set_safety_limit(self, active: bool, message: str = ""):
        """Publish the active mount safety interlock state for UI/remote clients."""
        with self._lock:
            self.safety_limit_active = bool(active)
            self.safety_limit_message = message if active else ""

    # ─── RELAY PAYLOAD BUILDER ─────────────────────────────────
    def build_relay_payload(self) -> bytes:
        """
        Build the 7-byte relay payload for `:UXXXXXXX#` protocol.

        Returns the raw nibbles (before | 0x30 encoding).
        The caller (ControlSerial) applies the encoding.

        Byte layout:
          [0] c_rah: RA Coarse E/W, Fine1 E/W
          [1] c_ral: RA Fine2 E/W, Track OFF/ON
          [2] c_dech: DEC Coarse N/S, Fine1 N/S
          [3] c_decl: DEC Fine2 N/S, (reserved)
          [4] c_dome: CW, CCW, OFF, OFF_BAR
          [5] c_acc: Accessories (TF, Mirror Flap)
          [6] c_console: Reserved
        """
        with self._lock:
            c_rah = 0x00
            c_ral = 0x00
            c_dech = 0x00
            c_decl = 0x00
            c_dome = 0x00
            c_acc = 0x00
            c_console = 0x00

            # Determine effective RA speed/direction
            # Manual jog overrides auto-slew
            eff_ra_speed = self.ra_speed if self.ra_direction != "NONE" else self.slew_ra_speed
            eff_ra_dir = self.ra_direction if self.ra_direction != "NONE" else (
                "WEST" if self.slew_ra_dir > 0 else "EAST" if self.slew_ra_dir < 0 else "NONE"
            )
            # Use slew speed when auto-slewing
            if self.ra_direction == "NONE" and self.slew_ra_speed:
                eff_ra_speed = self.slew_ra_speed

            # Determine effective DEC speed/direction
            eff_dec_speed = self.dec_speed if self.dec_direction != "NONE" else self.slew_dec_speed
            eff_dec_dir = self.dec_direction if self.dec_direction != "NONE" else (
                "NORTH" if self.slew_dec_dir > 0 else "SOUTH" if self.slew_dec_dir < 0 else "NONE"
            )
            if self.dec_direction == "NONE" and self.slew_dec_speed:
                eff_dec_speed = self.slew_dec_speed

            # ─── PACK RA BITS ───
            if eff_ra_dir != "NONE" and eff_ra_speed:
                if eff_ra_speed == "COARSE":
                    if eff_ra_dir == "EAST":
                        c_rah |= 0x08  # Pin 5
                    else:
                        c_rah |= 0x04  # Pin 6
                elif eff_ra_speed == "FINE_1":
                    if eff_ra_dir == "EAST":
                        c_rah |= 0x02  # Pin 7
                    else:
                        c_rah |= 0x01  # Pin 8
                elif eff_ra_speed == "FINE_2":
                    if eff_ra_dir == "EAST":
                        c_ral |= 0x08  # Pin 9
                    else:
                        c_ral |= 0x04  # Pin 10

            # ─── PACK TRACK BITS (legacy-duration pulses) ───
            if self._pulse_track_off_ticks > 0:
                c_ral |= 0x01  # Re-mapped to Pin 12 based on real hardware testing
                self._pulse_track_off_ticks -= 1
            if self._pulse_track_on_ticks > 0:
                c_ral |= 0x02  # Re-mapped to Pin 11 based on real hardware testing
                self._pulse_track_on_ticks -= 1

            # ─── PACK DEC BITS ───
            if eff_dec_dir != "NONE" and eff_dec_speed:
                if eff_dec_speed == "COARSE":
                    if eff_dec_dir == "NORTH":
                        c_dech |= 0x08  # Pin 14
                    else:
                        c_dech |= 0x04  # Pin 15
                elif eff_dec_speed == "FINE_1":
                    if eff_dec_dir == "NORTH":
                        c_dech |= 0x02  # Pin 16
                    else:
                        c_dech |= 0x01  # Pin 17
                elif eff_dec_speed == "FINE_2":
                    if eff_dec_dir == "NORTH":
                        c_decl |= 0x08  # Pin 18
                    else:
                        c_decl |= 0x04  # Pin 19

            # ─── PACK DOME BITS (one-shot pulses) ───
            if self._pulse_dome_cw:
                c_dome |= 0x08  # Pin 26: CW
                self._pulse_dome_cw = False
            if self._pulse_dome_ccw:
                c_dome |= 0x04  # Pin 27: CCW
                self._pulse_dome_ccw = False
            if self._pulse_dome_off:
                c_dome |= 0x02  # Pin 28: OFF
                self._pulse_dome_off = False

            return bytes([c_rah, c_ral, c_dech, c_decl, c_dome, c_acc, c_console])

    # ─── SNAPSHOT FOR UI ───────────────────────────────────────
    def get_status_snapshot(self) -> dict:
        """Returns a copy of current state for UI display."""
        with self._lock:
            return {
                "ra_speed": self.ra_speed,
                "ra_direction": self.ra_direction,
                "dec_speed": self.dec_speed,
                "dec_direction": self.dec_direction,
                "tracking": self.tracking_active,
                "dome_state": self.dome_state,
                "is_slewing": self.is_slewing,
                "mode": self.mode,
                "sim_ha_deg": self.sim_ha_deg,
                "sim_dec_deg": self.sim_dec_deg,
                "telescope_position_valid": self.telescope_position_valid,
                "telescope_position_error": self.telescope_position_error,
                "safety_limit_active": self.safety_limit_active,
                "safety_limit_message": self.safety_limit_message,
                "cooldown_active": self.cooldown_active,
            }
