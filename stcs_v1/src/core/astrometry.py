# stcs_v1/src/core/astrometry.py
import time as _time
import math
import numpy as np
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.time import Time
from astropy import units as u
from astropy.utils import iers
import warnings
from datetime import datetime, timezone

# --- FIX FOR IERS SSL ERROR ---
# Disable auto-downloading of IERS data to prevent SSL errors.
# Also allow using predictive values older than 30 days to avoid crashes.
# The built-in table is sufficient for standard telescope pointing.
iers.conf.auto_download = True
iers.conf.auto_max_age = None 
warnings.filterwarnings('ignore', category=iers.IERSWarning)

class AstrometryEngine:
    """
    Handles astronomical calculations like LST, HRA, AirMass, and AZ/EL conversions.
    Now supports dynamic updates from live GPS data (Time, Lat, Lon, Alt).

    Performance: LST and AltAz transforms are cached to avoid redundant
    Astropy calls from the 10Hz control loop, Alpaca server, and UI.
    """
    # Cache staleness thresholds (seconds)
    LST_CACHE_TTL = 0.2       # 200ms — LST drifts ~0.0008° in this window
    ALTAZ_CACHE_TTL = 1.0     # 1s   — AltAz changes slowly enough

    def __init__(self):
        # Coordinates from aries1.c:
        # eLong = 79.45799, eLat = 29.3586, Height ~1951m (ARIES)
        self.default_lat = 29.3586
        self.default_lon = 79.45799
        self.default_height = 1951
        self.location = EarthLocation(lat=self.default_lat*u.deg, lon=self.default_lon*u.deg, height=self.default_height*u.m)

        # State variables for GPS overrides
        self.live_utc_time = None
        self.live_utc_monotonic = None
        self._last_gps_utc_dt = None   # Track last accepted GPS datetime to reject stale duplicates

        # ── LST cache ──
        self._lst_cache_hours = 0.0
        self._lst_cache_time = 0.0    # monotonic timestamp

        # ── AltAz cache ──
        self._altaz_cache = {}        # result dict
        self._altaz_cache_ra = None
        self._altaz_cache_dec = None
        self._altaz_cache_time = 0.0  # monotonic timestamp

    def update_from_gps(self, gps_data):
        """
        Updates the EarthLocation and current UTC time based on live GPS telemetry.

        IMPORTANT: The GPS driver emits current_data on every GGA *and* RMC sentence,
        but utc_time is only refreshed by RMC. GGA re-emits the stale utc_time from
        the previous RMC. If we blindly reset live_utc_monotonic on every call, the
        interpolated clock jumps backward each time a GGA arrives with old time.
        Fix: only accept utc_time if it is strictly newer than the last accepted value.
        """
        if not gps_data or gps_data.get("fix_quality", 0) == 0:
            return # Keep using defaults/system clock if no fix

        lat = gps_data.get("latitude", self.default_lat)
        lon = gps_data.get("longitude", self.default_lon)
        alt = gps_data.get("altitude", self.default_height)

        try:
            lat = float(lat)
            lon = float(lon)
            alt = float(alt)
        except (TypeError, ValueError):
            return

        if not (math.isfinite(lat) and math.isfinite(lon) and math.isfinite(alt)):
            return
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return

        # Update location dynamically
        self.location = EarthLocation(lat=lat*u.deg, lon=lon*u.deg, height=alt*u.m)
        self._altaz_cache_time = 0.0

        # Update time ONLY if the GPS provides a strictly newer timestamp.
        # This prevents GGA sentences (which carry stale utc_time from the
        # last RMC) from resetting the monotonic anchor and causing LST
        # to jump backward.
        dt = gps_data.get("utc_time")
        if dt is not None:
            # Ensure it's timezone aware (UTC) before comparison
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # Only accept if strictly newer than the last accepted time
            if self._last_gps_utc_dt is None or dt > self._last_gps_utc_dt:
                self._last_gps_utc_dt = dt
                self.live_utc_time = Time(dt)
                self.live_utc_monotonic = _time.monotonic()

    def _get_current_time(self):
        """Returns the GPS time (with sub-second interpolation) if available, otherwise falls back to system clock."""
        if self.live_utc_time is not None and self.live_utc_monotonic is not None:
            elapsed = _time.monotonic() - self.live_utc_monotonic
            return self.live_utc_time + elapsed * u.second
        return Time.now()

    def calculate_parameters(self, ra_hours, dec_deg):
        """
        Input: Current Telescope RA (decimal hours) and DEC (decimal degrees).
        Output: Dictionary with HRA, LST, AZ, EL, AirMass.
        """
        current_time = _time.monotonic()
        
        # Check AltAz cache
        if (self._altaz_cache_ra == ra_hours and 
            self._altaz_cache_dec == dec_deg and 
            (current_time - self._altaz_cache_time) < self.ALTAZ_CACHE_TTL):
            return self._altaz_cache

        # 1. Current Time (UTC)
        now = self._get_current_time()

        # 2. Calculate LST (Local Sidereal Time) - bypass get_current_lst_hours_cached since we have 'now'
        lst = now.sidereal_time('mean', longitude=self.location.lon)
        lst_hours = lst.hour
        
        # Update LST cache since we just calculated it
        self._lst_cache_hours = lst_hours
        self._lst_cache_time = current_time

        # 3. Calculate HRA (Hour Angle)
        # HRA = LST - RA
        hra_hours = lst_hours - ra_hours
        # Normalize to -12 to +12 range or 0-24
        if hra_hours < 0:
            hra_hours += 24.0

        # 4. Calculate AZ / EL (Horizontal Coordinates)
        # Create SkyCoord object for the target
        target = SkyCoord(ra=ra_hours*u.hour, dec=dec_deg*u.deg, frame='icrs')
        # Convert to AltAz frame at current location and time
        altaz_frame = AltAz(obstime=now, location=self.location)
        target_altaz = target.transform_to(altaz_frame)

        az_deg = target_altaz.az.deg
        alt_deg = target_altaz.alt.deg

        # 5. Calculate Air Mass
        # Simple approximation: AirMass = 1 / cos(Zenith Angle) = 1 / sin(Elevation)
        # astropy has a built-in method usually, or we use secz
        airmass = target_altaz.secz.value
        # Handle below horizon cases
        if airmass < 0 or alt_deg < 0:
            airmass = 99.9

        result = {
            "lst_decimal": lst_hours,
            "hra_decimal": hra_hours,
            "az_deg": az_deg,
            "alt_deg": alt_deg,
            "airmass": airmass,
            "jd": now.jd
        }
        
        # Update cache
        self._altaz_cache = result
        self._altaz_cache_ra = ra_hours
        self._altaz_cache_dec = dec_deg
        self._altaz_cache_time = current_time
        
        return result

    def get_current_lst_hours(self):
        """
        Returns the current Local Sidereal Time (LST) in decimal hours.
        """
        now = self._get_current_time()
        lst = now.sidereal_time('mean', longitude=self.location.lon)
        
        lst_hours = lst.hour
        self._lst_cache_hours = lst_hours
        self._lst_cache_time = _time.monotonic()
        
        return lst_hours

    def get_current_lst_hours_cached(self):
        """
        Returns cached LST if fresh enough, else recalculates.
        Huge CPU saving for 10Hz loops and Alpaca server queries.
        """
        if (_time.monotonic() - self._lst_cache_time) < self.LST_CACHE_TTL:
            return self._lst_cache_hours
        return self.get_current_lst_hours()

    @staticmethod
    def decimal_hours_to_hms_string(val):
        h = int(val)
        m = int((val - h) * 60)
        s = (val - h - m/60) * 3600
        return f"{h:02d}:{m:02d}:{s:04.1f}"
