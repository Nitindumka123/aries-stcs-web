# src/core/simulation_engine.py
"""
Simulation Physics Engine.

When TELESCOPE_MODE=SIMULATION, this thread simulates telescope
position by applying motion speeds based on the current MotionState.
Replaces encoder hardware for testing/development.

Speeds (degrees/second):
  COARSE:  2.0
  FINE_1:  0.05
  FINE_2:  0.002777
  TRACK:   0.004178074 (True Sidereal Rate)
"""
import time
import logging
from PyQt6.QtCore import QThread, pyqtSignal

from src.core.motion_state import MotionState, SPEEDS

logger = logging.getLogger("SimulationEngine")


class SimulationEngine(QThread):
    """
    Background thread that simulates telescope position at 10Hz.
    Only active when MotionState.mode == "SIMULATION".
    
    Emits telemetry_updated with simulated position data for the UI.
    """
    telemetry_updated = pyqtSignal(dict)
    log_message = pyqtSignal(str)

    def __init__(self, motion_state: MotionState):
        super().__init__()
        self.state = motion_state
        self.running = False

    def run(self):
        self.running = True
        hz = 10.0
        sleep_time = 1.0 / hz
        last_time = time.time()

        logger.info("Simulation engine started at 10Hz.")

        while self.running:
            current_time = time.time()
            dt = current_time - last_time
            last_time = current_time

            if self.state.mode != "SIMULATION":
                time.sleep(sleep_time)
                continue

            with self.state._lock:
                # Apply tracking rate (adds to HA continuously)
                if self.state.tracking_active:
                    self.state.sim_ha_deg += SPEEDS['TRACK'] * dt

                # Determine effective RA motion
                eff_ra_speed = None
                eff_ra_dir = 0

                if self.state.ra_direction != "NONE":
                    # Manual jog
                    eff_ra_speed = self.state.ra_speed
                    eff_ra_dir = -1 if self.state.ra_direction == "EAST" else 1
                elif self.state.slew_ra_speed:
                    # Auto-slew
                    eff_ra_speed = self.state.slew_ra_speed
                    eff_ra_dir = self.state.slew_ra_dir

                if eff_ra_speed and eff_ra_dir != 0:
                    self.state.sim_ha_deg += eff_ra_dir * SPEEDS[eff_ra_speed] * dt

                # Determine effective DEC motion
                eff_dec_speed = None
                eff_dec_dir = 0

                if self.state.dec_direction != "NONE":
                    eff_dec_speed = self.state.dec_speed
                    eff_dec_dir = 1 if self.state.dec_direction == "NORTH" else -1
                elif self.state.slew_dec_speed:
                    eff_dec_speed = self.state.slew_dec_speed
                    eff_dec_dir = self.state.slew_dec_dir

                if eff_dec_speed and eff_dec_dir != 0:
                    self.state.sim_dec_deg += eff_dec_dir * SPEEDS[eff_dec_speed] * dt

                # Normalize HA to -180..+180
                self.state.sim_ha_deg = (self.state.sim_ha_deg + 180) % 360 - 180

            time.sleep(sleep_time)

        logger.info("Simulation engine stopped.")

    def stop(self):
        self.running = False
        self.wait()
