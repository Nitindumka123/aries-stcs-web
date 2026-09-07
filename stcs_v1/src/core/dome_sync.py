# src/core/dome_sync.py
import os
import time
import logging
import math
from PyQt6.QtCore import QThread, pyqtSignal
from src.core.dome_geometry import corrected_dome_azimuth

logger = logging.getLogger("DomeSync")

class DomeSyncWorker(QThread):
    sync_finished = pyqtSignal(str)
    
    def __init__(self, motion_state, astro, park_mode=False):
        super().__init__()
        self.motion_state = motion_state
        self.astro = astro
        self.park_mode = park_mode
        self._abort = False
        
    def abort(self):
        self._abort = True
        
    def run(self):
        self._abort = False
        try:
            # Load parameters from .env
            speed_dps = float(os.environ.get("DOME_MAX_SPEED_DPS", "1.354"))
            ramp_time_s = float(os.environ.get("DOME_RAMP_TIME_S", "5.0"))
            
            # Allow direct override of coast distance
            coast_distance = float(os.environ.get("DOME_COAST_DEG", str((speed_dps * ramp_time_s) / 2.0)))
            target_details = {}
            
            def get_target_az():
                nonlocal target_details
                if self.park_mode:
                    target_details = {
                        "telescope_az": 0.0,
                        "telescope_alt": 0.0,
                        "ha_deg": 0.0,
                        "target_az": 0.0,
                    }
                    return 0.0
                with self.motion_state._lock:
                    position_valid = getattr(self.motion_state, "telescope_position_valid", True)
                    position_error = getattr(self.motion_state, "telescope_position_error", "")
                    ha_deg = self.motion_state.sim_ha_deg
                    dec_deg = self.motion_state.sim_dec_deg

                if not position_valid:
                    raise RuntimeError(position_error or "Telescope position is invalid; dome sync aborted.")
                if not math.isfinite(dec_deg) or not -90.0 <= dec_deg <= 90.0:
                    raise RuntimeError(
                        f"Invalid telescope DEC for dome sync: {dec_deg:.6f}°. "
                        "Check DEC encoder/home calibration before syncing the dome."
                    )

                lst_hours = self.astro.get_current_lst_hours_cached()
                ha_hours = ha_deg / 15.0
                ra_hours = (lst_hours - ha_hours) % 24.0
                
                astro_params = self.astro.calculate_parameters(ra_hours, dec_deg)
                telescope_az = astro_params.get("az_deg", 0.0)
                telescope_alt = astro_params.get("alt_deg", 0.0)
                site_lat = self.astro.location.lat.deg
                target_az = corrected_dome_azimuth(telescope_az, telescope_alt, ha_deg, site_lat)
                target_details = {
                    "telescope_az": telescope_az,
                    "telescope_alt": telescope_alt,
                    "ha_deg": ha_deg,
                    "target_az": target_az,
                }
                return target_az
                
            initial_target_az = get_target_az()
            
            start_az = self.motion_state.dome_az_deg
            
            delta = initial_target_az - start_az
            if delta < -180: delta += 360
            elif delta > 180: delta -= 360
            
            if abs(delta) <= coast_distance:
                self.sync_finished.emit(f"Dome already near target (within {coast_distance:.1f}°).")
                return
                
            direction = "CW" if delta > 0 else "CCW"
            logger.info(
                f"Dome Sync Started: Target AZ={initial_target_az:.1f}°, Current={start_az:.1f}°, "
                f"Coasting={coast_distance:.1f}°, Telescope AZ={target_details.get('telescope_az', 0.0):.1f}°, "
                f"ALT={target_details.get('telescope_alt', 0.0):.1f}°, HA={target_details.get('ha_deg', 0.0):.1f}°"
            )
            
            if direction == "CW":
                self.motion_state.set_dome_cw()
            else:
                self.motion_state.set_dome_ccw()
                
            while not self._abort:
                target_az = get_target_az()

                current_az = self.motion_state.dome_az_deg
                
                dist = target_az - current_az
                if dist < -180: dist += 360
                elif dist > 180: dist -= 360
                
                # Check if we reached the stopping point
                # If moving CW, dist will be positive and decreasing.
                # If moving CCW, dist will be negative and increasing (towards 0).
                if direction == "CW" and dist <= coast_distance:
                    break
                if direction == "CCW" and dist >= -coast_distance:
                    break
                    
                time.sleep(0.1)
                
            self.motion_state.set_dome_off()
            
            if self._abort:
                logger.info("Dome Sync aborted.")
                self.sync_finished.emit("Dome Sync aborted.")
            else:
                logger.info(f"Dome Sync early stop triggered (coasting {coast_distance:.1f}°).")
                self.sync_finished.emit(
                    f"Dome Sync stop: target {target_details.get('target_az', initial_target_az):.1f}°, "
                    f"scope AZ {target_details.get('telescope_az', 0.0):.1f}°, "
                    f"ALT {target_details.get('telescope_alt', 0.0):.1f}°."
                )
                
        except Exception as e:
            logger.error(f"Dome Sync failed: {e}")
            self.sync_finished.emit(f"Dome Sync Error: {e}")
            self.motion_state.set_dome_off()
