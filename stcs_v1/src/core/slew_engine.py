# src/core/slew_engine.py
"""
Smart Slew Engine with Waypoint Route Planner.

Ported from telescope_control_gui.py. Handles automated slewing:
- Direct slew when path is safe
- Waypoint routing via higher DEC when altitude limit blocks direct path
- Speed selection based on pointing error thresholds
- 6-second cooldown after slew completion
"""
import logging
import time
import json
import os
import threading
from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
import astropy.units as u

from src.core.motion_state import MotionState, THRESH_COARSE, TOLERANCE
from src.core.astrometry import AstrometryEngine
from src.core.safety import load_motion_limits

logger = logging.getLogger("SlewEngine")

# Fine 2 is reserved for the coordinate minute field:
#   RA:  1 minute of RA time = 0.25 degrees of hour angle
#   DEC: 1 arcminute       = 1/60 degree
FINE2_ENTRY_THRESHOLD_DEG = {
    "RA": 0.25,
    "DEC": 1.0 / 60.0,
}

SPEED_RANK = {
    "FINE_2": 1,
    "FINE_1": 2,
    "COARSE": 3,
}


class SlewEngine:
    """
    Manages automated slew-to-target with waypoint obstacle avoidance.
    
    Usage:
        engine = SlewEngine(motion_state, astrometry_engine)
        engine.start_slew(target_ra_deg, target_dec_deg)
        # Call update() at 10Hz to drive the slew
        engine.update()
    """

    def __init__(self, motion_state: MotionState, astro: AstrometryEngine):
        self.state = motion_state
        self.astro = astro

        # Slew routing state
        self.final_target_ra = None
        self.final_target_dec = None
        self.waypoint_ra = None
        self.waypoint_dec = None
        self.routing_mode = "DIRECT"  # DIRECT or WAYPOINT
        self.waypoint_phase = 0       # 1 = heading to waypoint, 2 = heading to target

        # Sequential axis logic
        self.slew_phase = "IDLE"      # IDLE, FIRST_AXIS, SECOND_AXIS
        self.first_axis = None        # "RA" or "DEC"

        # Reversal protection (Slip compensation)
        self._last_ra_dir = 0
        self._last_dec_dir = 0
        self._ra_cooldown_until = 0.0
        self._dec_cooldown_until = 0.0
        self._ra_settle_until = 0.0
        self._dec_settle_until = 0.0
        self._slip_config = self._load_slip_config()

        # Limits
        limits = load_motion_limits()
        self.min_alt = float(limits.get("min_altitude_deg", 45.0))
        self.max_alt = float(limits.get("max_altitude_deg", 89.0))
        self.min_dec = float(limits.get("min_declination_deg", -50.0))
        self.max_dec = float(limits.get("max_declination_deg", 70.0))

        self._lock = threading.Lock()
        self._last_ra_speed_active = None
        self._last_dec_speed_active = None

        # Speed transition delay: pause the motor for N seconds when
        # slew speed changes (e.g. COARSE → FINE_1) to protect gears.
        self.SPEED_TRANSITION_DELAY_SEC = float(os.environ.get("SLEW_SPEED_TRANSITION_DELAY_SEC", "0.5"))
        self._last_ra_speed_applied = None   # Last speed actually sent to motor
        self._last_dec_speed_applied = None
        self._ra_speed_transition_until = 0.0  # Timestamp: motor OFF until this time
        self._dec_speed_transition_until = 0.0

        # Fixed HA targeting (for park operations)
        # When set, update() recalculates final_target_ra from current LST
        # each tick so the physical HA target remains pinned.
        self._fixed_ha_deg = None

    def _load_slip_config(self):
        try:
            base_path = os.environ.get('STCS_EXTERNAL_ROOT', os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
            path = os.path.join(base_path, 'config', 'slip_calibration.json')
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load slip_calibration.json: {e}. Using defaults.")
            default_ax = {
                "COARSE": {"slip_deg": 0.5, "cooldown_sec": 3.0},
                "FINE_1": {"slip_deg": 0.05, "cooldown_sec": 1.0},
                "FINE_2": {"slip_deg": 0.005, "cooldown_sec": 0.2}
            }
            return {"RA": default_ax, "DEC": default_ax}

    def _get_deadband(self, axis, speed_tier):
        if speed_tier is None or self.state.mode == "SIMULATION":
            return 0.0
        return self._slip_config.get(axis, {}).get(speed_tier, {}).get("slip_deg", 0.0)

    def _get_reversal_cooldown(self, axis, speed_tier):
        if speed_tier is None:
            return 0.0
        return self._slip_config.get(axis, {}).get(speed_tier, {}).get("cooldown_sec", 0.0)

    def _get_location(self):
        return self.astro.location

    def _get_lst_degrees(self):
        return self.astro.get_current_lst_hours_cached() * 15.0

    def _ra_to_ha(self, ra_deg):
        ha = self._get_lst_degrees() - ra_deg
        return (ha + 180) % 360 - 180

    def _ha_to_ra(self, ha_deg):
        return (self._get_lst_degrees() - ha_deg) % 360

    def check_destination_limits(self, target_ra_deg, target_dec_deg, skip_max_alt=False):
        """Check if target is within safe limits.
        
        Args:
            skip_max_alt: If True, bypass the upper altitude (zenith) limit.
                          Used by park operations where the target is intentionally
                          near the zenith and tracking is not a concern.
        """
        if target_dec_deg < self.min_dec or target_dec_deg > self.max_dec:
            return False, f"Declination ({target_dec_deg:.1f}°) out of limits."

        coord = SkyCoord(ra=target_ra_deg * u.deg, dec=target_dec_deg * u.deg, frame='icrs')
        altaz = coord.transform_to(AltAz(
            obstime=self.astro._get_current_time(),
            location=self._get_location()
        ))

        if altaz.alt.deg < self.min_alt:
            return False, f"Altitude ({altaz.alt.deg:.1f}°) below {self.min_alt:.1f}° safety limit."
        if not skip_max_alt and altaz.alt.deg > self.max_alt:
            return False, f"Altitude ({altaz.alt.deg:.1f}°) out of limits."

        return True, "Target safe."

    def _is_path_safe(self, start_ra, start_dec, target_ra, target_dec, steps=10):
        """Sample path at N points and check altitude at each."""
        t_now = self.astro._get_current_time()
        diff_ra = (target_ra - start_ra + 180) % 360 - 180

        for i in range(steps + 1):
            f = i / float(steps)
            test_ra = (start_ra + f * diff_ra) % 360
            test_dec = start_dec + f * (target_dec - start_dec)

            coord = SkyCoord(ra=test_ra * u.deg, dec=test_dec * u.deg, frame='icrs')
            altaz = coord.transform_to(AltAz(obstime=t_now, location=self._get_location()))

            if altaz.alt.deg < self.min_alt:
                return False
        return True

    def start_slew(self, target_ra_deg, target_dec_deg, skip_max_alt=False, fixed_ha_deg=None):
        """
        Plan and begin a slew to target. Returns (success, message).
        
        Args:
            skip_max_alt: If True, bypass upper altitude limit check.
                          Used for parking near the zenith.
            fixed_ha_deg: If set, the slew targets a fixed Hour Angle instead
                          of a fixed RA. The RA target is recalculated from
                          current LST on every update tick so the physical
                          HA stays pinned. Used for parking to HRA=0.
        """
        safe, msg = self.check_destination_limits(target_ra_deg, target_dec_deg, skip_max_alt=skip_max_alt)
        if not safe:
            return False, msg

        if self.state.cooldown_active:
            return False, "Motors in cooldown. Wait before slewing."

        # Store fixed HA target (if parking)
        self._fixed_ha_deg = fixed_ha_deg

        start_ra = self._ha_to_ra(self.state.sim_ha_deg)
        start_dec = self.state.sim_dec_deg

        self.final_target_ra = target_ra_deg
        self.final_target_dec = target_dec_deg

        with self.state._lock:
            self.state.is_slewing = True

        # Slew path planning
        if self._is_path_safe(start_ra, start_dec, target_ra_deg, target_dec_deg):
            self.routing_mode = "DIRECT"
            msg = f"Direct Slew to RA {target_ra_deg:.2f}°, DEC {target_dec_deg:.2f}°"
            logger.info(msg)
        else:
            # Plan waypoint route
            diff_ra = (target_ra_deg - start_ra + 180) % 360 - 180
            mid_ra = (start_ra + diff_ra / 2.0) % 360

            candidate_dec = max(start_dec, target_dec_deg)
            safe_wp_dec = None

            while candidate_dec <= self.max_dec:
                leg_1_safe = self._is_path_safe(start_ra, start_dec, mid_ra, candidate_dec)
                leg_2_safe = self._is_path_safe(mid_ra, candidate_dec, target_ra_deg, target_dec_deg)

                if leg_1_safe and leg_2_safe:
                    safe_wp_dec = candidate_dec
                    break
                candidate_dec += 2.0

            if safe_wp_dec is None:
                safe_wp_dec = self.max_dec

            self.waypoint_ra = mid_ra
            self.waypoint_dec = safe_wp_dec
            self.routing_mode = "WAYPOINT"
            self.waypoint_phase = 1

            msg = f"Waypoint Route via DEC +{safe_wp_dec:.1f}°"
            logger.info(msg)

        # ALWAYS plan sequential movement for safety
        self._determine_axis_priority(
            start_ra, start_dec,
            temp_ra=self.waypoint_ra if self.routing_mode == "WAYPOINT" else target_ra_deg,
            temp_dec=self.waypoint_dec if self.routing_mode == "WAYPOINT" else target_dec_deg
        )

        return True, msg

    def _determine_axis_priority(self, start_ra, start_dec, temp_ra, temp_dec):
        """Determine whether to move RA or DEC first to maximize altitude safety."""
        t_now = self.astro._get_current_time()
        
        # Test path 1: RA first, then DEC
        coord1 = SkyCoord(ra=temp_ra * u.deg, dec=start_dec * u.deg, frame='icrs')
        alt1 = coord1.transform_to(AltAz(obstime=t_now, location=self._get_location())).alt.deg
        
        # Test path 2: DEC first, then RA
        coord2 = SkyCoord(ra=start_ra * u.deg, dec=temp_dec * u.deg, frame='icrs')
        alt2 = coord2.transform_to(AltAz(obstime=t_now, location=self._get_location())).alt.deg
        
        self.slew_phase = "FIRST_AXIS"
        if alt1 > alt2:
            self.first_axis = "RA"
        else:
            self.first_axis = "DEC"
            
        logger.info(f"Axis priority: {self.first_axis} first (intermediate alts: RA-first={alt1:.1f}°, DEC-first={alt2:.1f}°)")

    def update(self):
        """
        Called at 10Hz. Calculates speed/direction based on pointing error.
        Updates MotionState.slew_ra_speed/dir and slew_dec_speed/dir.
        
        Returns a status message string or None.
        """
        with self._lock:
            if not self.state.is_slewing or self.final_target_ra is None:
                return None

        # Fixed HA mode: recalculate RA target from current LST each tick
        # so the physical HA target stays pinned regardless of time progression.
        if self._fixed_ha_deg is not None:
            self.final_target_ra = self._ha_to_ra(self._fixed_ha_deg)

        # Determine current target (waypoint or final)
        if self.routing_mode == "WAYPOINT" and self.waypoint_phase == 1:
            temp_target_ra = self.waypoint_ra
            temp_target_dec = self.waypoint_dec
        else:
            temp_target_ra = self.final_target_ra
            temp_target_dec = self.final_target_dec

        # Calculate errors
        target_ha = self._ra_to_ha(temp_target_ra)
        ha_error = (target_ha - self.state.sim_ha_deg + 180) % 360 - 180
        dec_error = temp_target_dec - self.state.sim_dec_deg

        current_time = time.time()

        # Calculate raw speed selection from error (with Early Cutoff)
        ra_speed, ra_raw_dir = self._calc_axis_speed_dir("RA", ha_error)
        dec_speed, dec_raw_dir = self._calc_axis_speed_dir("DEC", dec_error)

        # Handle Settle Phase (Coasting)
        # If we are in settle phase, force motor OFF regardless of error
        if current_time < self._ra_settle_until:
            ra_speed, ra_raw_dir = None, 0
        if current_time < self._dec_settle_until:
            dec_speed, dec_raw_dir = None, 0

        # Apply sequential constraint
        if self.slew_phase == "FIRST_AXIS":
            if self.first_axis == "RA":
                if ra_speed is None and current_time >= self._ra_settle_until:
                    # RA arrived AND settled
                    self.slew_phase = "SECOND_AXIS"
                else:                 # RA moving or settling, DEC stopped
                    dec_speed, dec_raw_dir = None, 0
            else: # DEC first
                if dec_speed is None and current_time >= self._dec_settle_until:
                    # DEC arrived AND settled
                    self.slew_phase = "SECOND_AXIS"
                else:                 # DEC moving or settling, RA stopped
                    ra_speed, ra_raw_dir = None, 0

        # Detect if we are TRANSITIONING from moving to stopped (Early Cutoff trigger)
        # Only log once and only if we were actually moving
        if self._last_ra_dir != 0 and ra_raw_dir == 0 and current_time >= self._ra_settle_until:
            if self._last_ra_speed_active:
                settle_dur = self._get_reversal_cooldown("RA", self._last_ra_speed_active)
                self._ra_settle_until = current_time + settle_dur
                logger.info(f"RA reached slip threshold. Coasting for {settle_dur}s.")
            self._last_ra_dir = 0 # Signal stationary
            ra_speed, ra_raw_dir = None, 0

        if self._last_dec_dir != 0 and dec_raw_dir == 0 and current_time >= self._dec_settle_until:
            if self._last_dec_speed_active:
                settle_dur = self._get_reversal_cooldown("DEC", self._last_dec_speed_active)
                self._dec_settle_until = current_time + settle_dur
                logger.info(f"DEC reached slip threshold. Coasting for {settle_dur}s.")
            self._last_dec_dir = 0 # Signal stationary
            dec_speed, dec_raw_dir = None, 0

        # When stepping down to a slower speed, stop first and let the mount
        # settle using the outgoing speed's coast time. Then re-measure error
        # before engaging the next speed tier.
        ra_speed, ra_raw_dir = self._apply_downshift_settle(
            "RA", ra_speed, ra_raw_dir, current_time
        )
        dec_speed, dec_raw_dir = self._apply_downshift_settle(
            "DEC", dec_speed, dec_raw_dir, current_time
        )

        # Apply Reversal Protection (Hysteresis & Cooldown)
        ra_dir, self._last_ra_dir = self._apply_reversal_protection(
            "RA", ha_error, ra_speed, ra_raw_dir, self._last_ra_dir, current_time
        )
        dec_dir, self._last_dec_dir = self._apply_reversal_protection(
            "DEC", dec_error, dec_speed, dec_raw_dir, self._last_dec_dir, current_time
        )
        
        # Track active speed for cooldown lookup after stop
        if ra_speed: self._last_ra_speed_active = ra_speed
        if dec_speed: self._last_dec_speed_active = dec_speed

        # If anti-reversal logic forces DIR=0, we clear the speed
        if ra_dir == 0: ra_speed = None
        if dec_dir == 0: dec_speed = None

        # ── Speed Transition Delay ──
        # When slew speed changes (e.g. COARSE → FINE_1), pause the motor
        # for SPEED_TRANSITION_DELAY_SEC to protect gears and prevent
        # mechanical shock from abrupt speed changes.
        if ra_speed is not None and self._last_ra_speed_applied is not None:
            if ra_speed != self._last_ra_speed_applied:
                self._ra_speed_transition_until = current_time + self.SPEED_TRANSITION_DELAY_SEC
                logger.info(
                    f"RA speed transition: {self._last_ra_speed_applied} → {ra_speed}. "
                    f"Pausing {self.SPEED_TRANSITION_DELAY_SEC}s."
                )

        if dec_speed is not None and self._last_dec_speed_applied is not None:
            if dec_speed != self._last_dec_speed_applied:
                self._dec_speed_transition_until = current_time + self.SPEED_TRANSITION_DELAY_SEC
                logger.info(
                    f"DEC speed transition: {self._last_dec_speed_applied} → {dec_speed}. "
                    f"Pausing {self.SPEED_TRANSITION_DELAY_SEC}s."
                )

        # Enforce speed transition pause: motor OFF during transition
        if current_time < self._ra_speed_transition_until:
            ra_speed = None
            ra_dir = 0
        if current_time < self._dec_speed_transition_until:
            dec_speed = None
            dec_dir = 0

        # Track the speed we actually applied this tick
        self._last_ra_speed_applied = ra_speed
        self._last_dec_speed_applied = dec_speed

        # Update state immediately
        with self.state._lock:
            self.state.slew_ra_speed = ra_speed
            self.state.slew_ra_dir = ra_dir
            self.state.slew_dec_speed = dec_speed
            self.state.slew_dec_dir = dec_dir

        # Check if arrived at current target logic
        ra_done = (ra_speed is None) and (current_time >= self._ra_speed_transition_until) and (current_time >= self._ra_settle_until)
        dec_done = (dec_speed is None) and (current_time >= self._dec_speed_transition_until) and (current_time >= self._dec_settle_until)

        if self.slew_phase == "SECOND_AXIS" and ra_done and dec_done:
            if self.routing_mode == "WAYPOINT" and self.waypoint_phase == 1:
                # Waypoint cleared, move to final target
                self.waypoint_phase = 2
                
                # Re-calculate priority for final leg
                start_ra = self._ha_to_ra(self.state.sim_ha_deg)
                start_dec = self.state.sim_dec_deg
                self._determine_axis_priority(start_ra, start_dec, self.final_target_ra, self.final_target_dec)
                
                return "Waypoint cleared. Final approach..."
            else:
                self.slew_phase = "COMPLETE"
                with self.state._lock:
                    self.state.is_slewing = False
                    self.state.slew_ra_speed = None
                    self.state.slew_ra_dir = 0
                    self.state.slew_dec_speed = None
                    self.state.slew_dec_dir = 0
                    self.state.request_cooldown = True
                
                # IMPORTANT: Reset memory for next slew
                with self._lock:
                    self._last_ra_dir = 0
                    self._last_dec_dir = 0
                    self._last_ra_speed_active = None
                    self._last_dec_speed_active = None
                    self._ra_cooldown_until = 0
                    self._dec_cooldown_until = 0
                    self._ra_settle_until = 0
                    self._dec_settle_until = 0
                
                return "Slew complete. Target centered."

        return None

    def _calc_axis_speed_dir(self, axis, error):
        abs_err = abs(error)
        
        # Ensure thresholds are inherently larger than the slip distance to prevent 
        # getting stuck where error < threshold but motor still cuts off due to slip.
        # Add 10% buffer to the slip distance.
        coarse_slip = self._get_deadband(axis, 'COARSE')
        fine1_slip = self._get_deadband(axis, 'FINE_1')
        
        eff_thresh_coarse = max(THRESH_COARSE, coarse_slip * 1.1)
        fine2_entry = FINE2_ENTRY_THRESHOLD_DEG.get(axis, 1.0 / 60.0)
        eff_thresh_fine1 = max(fine2_entry, fine1_slip * 1.1)

        # Determine base speed from dynamic thresholds
        if abs_err > eff_thresh_coarse:
            speed = 'COARSE'
        elif abs_err > eff_thresh_fine1:
            speed = 'FINE_1'
        elif abs_err > TOLERANCE:
            speed = 'FINE_2'
        else:
            speed = None

        # Early Cutoff / Predictive Coasting:
        # If we are within the slip distance for the CURRENT speed, 
        # stop the motor early and let it coast.
        if speed:
            slip_deg = self._get_deadband(axis, speed)
            if abs_err <= slip_deg:
                logger.debug(f"{axis} within {speed} slip zone ({abs_err:.4f} <= {slip_deg:.4f}). Coasting...")
                speed = None

        direction = 1 if error > 0 and speed else (-1 if error < 0 and speed else 0)
        return speed, direction

    def _apply_downshift_settle(self, axis, selected_speed, selected_dir, now):
        if not selected_speed:
            return selected_speed, selected_dir

        if axis == "RA":
            last_speed = self._last_ra_speed_active
            last_dir = self._last_ra_dir
        else:
            last_speed = self._last_dec_speed_active
            last_dir = self._last_dec_dir

        is_downshift = (
            last_dir != 0
            and last_speed
            and selected_speed != last_speed
            and SPEED_RANK.get(selected_speed, 0) < SPEED_RANK.get(last_speed, 0)
        )
        if not is_downshift:
            return selected_speed, selected_dir

        settle_dur = max(
            self.SPEED_TRANSITION_DELAY_SEC,
            self._get_reversal_cooldown(axis, last_speed),
        )

        if axis == "RA":
            self._ra_settle_until = now + settle_dur
            self._last_ra_dir = 0
            self._last_ra_speed_active = None
            self._last_ra_speed_applied = None
        else:
            self._dec_settle_until = now + settle_dur
            self._last_dec_dir = 0
            self._last_dec_speed_active = None
            self._last_dec_speed_applied = None

        logger.info(
            f"{axis} downshift {last_speed} -> {selected_speed}: "
            f"coasting for {settle_dur}s before recheck."
        )
        return None, 0
        
    def _apply_reversal_protection(self, axis, error, selected_speed, intended_dir, last_dir, now):
        """
        Enforce dead-band hysteresis and cooldown on direction reversals.
        Returns the safe direction to engage (1, -1, or 0) and the updated last_dir.

        Three states for a reversal:
          1. First detection  → start cooldown timer, block motor
          2. Timer active     → keep blocking motor
          3. Timer expired    → allow new direction, reset timer
        """
        if intended_dir == 0:
            return 0, last_dir

        cooldown_timer = self._ra_cooldown_until if axis == "RA" else self._dec_cooldown_until

        # --- Active cooldown: block all motion regardless of direction ---
        if cooldown_timer > 0 and now < cooldown_timer:
            return 0, last_dir

        # --- Check if we are reversing direction ---
        if last_dir != 0 and intended_dir != last_dir:

            # Has a cooldown already been served for this reversal?
            if cooldown_timer > 0 and now >= cooldown_timer:
                # YES — cooldown complete. Clear timer and allow new direction.
                if axis == "RA":
                    self._ra_cooldown_until = 0
                else:
                    self._dec_cooldown_until = 0
                logger.info(f"{axis} reversal cooldown complete. Engaging new direction.")
                return intended_dir, intended_dir

            # NO — first detection of this reversal.
            # Apply dead-band hysteresis: if error is within slip zone, don't reverse
            deadband = self._get_deadband(axis, selected_speed)
            if abs(error) < deadband:
                return 0, last_dir

            # Error exceeds dead-band. Start cooldown timer.
            delay = self._get_reversal_cooldown(axis, selected_speed)
            if delay > 0:
                if axis == "RA":
                    self._ra_cooldown_until = now + delay
                else:
                    self._dec_cooldown_until = now + delay
                logger.info(f"{axis} reversing. Applying {delay}s cooldown.")
                return 0, last_dir
            else:
                # No cooldown configured — allow immediately
                return intended_dir, intended_dir

        # --- Same direction as before, or cold start (last_dir == 0) ---
        return intended_dir, intended_dir

    def abort(self):
        """Abort the current slew."""
        with self.state._lock:
            self.state.is_slewing = False
            self.state.slew_ra_speed = None
            self.state.slew_ra_dir = 0
            self.state.slew_dec_speed = None
            self.state.slew_dec_dir = 0
        
        with self._lock:
            self._last_ra_dir = 0
            self._last_dec_dir = 0
            self._last_ra_speed_active = None
            self._last_dec_speed_active = None
            self._ra_cooldown_until = 0
            self._dec_cooldown_until = 0
            self._ra_settle_until = 0
            self._dec_settle_until = 0

        self.final_target_ra = None
        self.final_target_dec = None
        self._fixed_ha_deg = None
        self.routing_mode = "DIRECT"
        self.waypoint_phase = 0
        self.slew_phase = "IDLE"

        # Reset speed transition state
        self._last_ra_speed_applied = None
        self._last_dec_speed_applied = None
        self._ra_speed_transition_until = 0
        self._dec_speed_transition_until = 0

        logger.info("Slew aborted.")
