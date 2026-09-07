import json
import logging
import math
import os

from src.core.motion_state import SPEEDS

logger = logging.getLogger("Safety")


def _project_root():
    external_root = os.environ.get("STCS_EXTERNAL_ROOT")
    if external_root:
        return external_root

    current = os.path.abspath(__file__)
    for _ in range(8):
        current = os.path.dirname(current)
        if os.path.exists(os.path.join(current, "config", "limits.json")):
            return current

    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_motion_limits():
    defaults = {
        "min_altitude_deg": 45.0,
        "max_altitude_deg": 89.0,
        "min_declination_deg": -50.0,
        "max_declination_deg": 70.0,
    }

    try:
        path = os.path.join(_project_root(), "config", "limits.json")
        with open(path, "r") as f:
            limits = json.load(f).get("motion", {})
        return {**defaults, **limits}
    except Exception as exc:
        logger.warning(f"Could not load config/limits.json: {exc}. Using defaults.")
        return defaults


class AltitudeSafetyGuard:
    """
    Predictive altitude interlock for mount motion.

    The guard blocks only motion that would push telescope altitude below the
    configured floor. If the telescope is already below the floor, motion that
    raises altitude is still allowed so operators can recover.
    """

    def __init__(self, astro, min_altitude_deg=None, lookahead_sec=1.0):
        self.astro = astro
        self.lookahead_sec = lookahead_sec
        limits = load_motion_limits()
        self.min_altitude_deg = (
            float(min_altitude_deg)
            if min_altitude_deg is not None
            else float(limits.get("min_altitude_deg", 45.0))
        )

    def reload_limits(self):
        limits = load_motion_limits()
        self.min_altitude_deg = float(limits.get("min_altitude_deg", 45.0))

    def altitude_for_mount_position(self, ha_deg, dec_deg):
        lst_hours = self.astro.get_current_lst_hours_cached()
        ra_hours = (lst_hours - (ha_deg / 15.0)) % 24.0
        return float(self.astro.calculate_parameters(ra_hours, dec_deg).get("alt_deg", float("nan")))

    def projected_altitude(self, ha_deg, dec_deg, ha_rate_deg_sec=0.0, dec_rate_deg_sec=0.0):
        projected_ha = ha_deg + ha_rate_deg_sec * self.lookahead_sec
        projected_dec = dec_deg + dec_rate_deg_sec * self.lookahead_sec
        projected_ha = (projected_ha + 180.0) % 360.0 - 180.0
        return self.altitude_for_mount_position(projected_ha, projected_dec)

    def motion_would_cross_floor(self, ha_deg, dec_deg, ha_rate_deg_sec=0.0, dec_rate_deg_sec=0.0):
        try:
            current_alt = self.altitude_for_mount_position(ha_deg, dec_deg)
            projected_alt = self.projected_altitude(
                ha_deg,
                dec_deg,
                ha_rate_deg_sec=ha_rate_deg_sec,
                dec_rate_deg_sec=dec_rate_deg_sec,
            )
        except Exception as exc:
            logger.error(f"Altitude safety calculation failed: {exc}")
            return True, float("nan"), float("nan")

        if not math.isfinite(current_alt) or not math.isfinite(projected_alt):
            return True, current_alt, projected_alt

        if projected_alt >= self.min_altitude_deg:
            return False, current_alt, projected_alt

        if current_alt < self.min_altitude_deg and projected_alt > current_alt:
            return False, current_alt, projected_alt

        return True, current_alt, projected_alt

    def ha_rate_for_ra_motion(self, speed_key, direction):
        if not speed_key or direction == 0:
            return 0.0
        return direction * SPEEDS.get(speed_key, 0.0)

    def dec_rate_for_dec_motion(self, speed_key, direction):
        if not speed_key or direction == 0:
            return 0.0
        return direction * SPEEDS.get(speed_key, 0.0)
