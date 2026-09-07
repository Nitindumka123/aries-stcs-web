import math
import os


def _env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def corrected_dome_azimuth(telescope_az_deg, telescope_alt_deg, ha_deg, site_lat_deg):
    """
    Return the dome slit azimuth for an off-center telescope.

    This ports the ARIES 104 cm dome-center correction from the legacy C code.
    The telescope azimuth points the optical axis; this function projects that
    axis from the real telescope position to the dome sphere and returns the
    azimuth where the beam intersects the dome.
    """
    fixed_offset_deg = _env_float("DOME_AZ_OFFSET", 0.0)
    if not _env_bool("DOME_GEOMETRY_ENABLED", False):
        return (telescope_az_deg + fixed_offset_deg) % 360.0

    dome_radius_m = _env_float("DOME_RADIUS_M", 5.31)
    optical_axis_offset_m = _env_float("DOME_OPTICAL_AXIS_OFFSET_M", 1.58)
    offset_x_m = _env_float("DOME_OFFSET_X_M", 0.0)
    offset_y_m = _env_float("DOME_OFFSET_Y_M", 0.0)
    offset_z_m = _env_float("DOME_OFFSET_Z_M", 1.2)

    az = math.radians(telescope_az_deg)
    alt = math.radians(telescope_alt_deg)
    ha = math.radians(ha_deg)
    lat = math.radians(site_lat_deg)

    x1 = offset_x_m + optical_axis_offset_m * math.cos(ha)
    y1 = offset_y_m - optical_axis_offset_m * math.sin(lat) * math.sin(ha)
    z1 = offset_z_m + optical_axis_offset_m * math.cos(lat) * math.sin(ha)

    distance_from_center_sq = x1 * x1 + y1 * y1 + z1 * z1
    ray_projection = (
        x1 * math.cos(alt) * math.sin(az)
        - y1 * math.cos(alt) * math.cos(az)
        + z1 * math.sin(alt)
    )
    discriminant = ray_projection * ray_projection - (
        distance_from_center_sq - dome_radius_m * dome_radius_m
    )

    if discriminant < 0.0:
        return (telescope_az_deg + fixed_offset_deg) % 360.0

    ray_distance = math.sqrt(discriminant) - ray_projection
    intersection_x = ray_distance * math.cos(alt) * math.sin(az) + x1
    intersection_y = ray_distance * math.cos(alt) * math.cos(az) - y1

    corrected_az = math.degrees(math.atan2(intersection_x, intersection_y))
    return (corrected_az + fixed_offset_deg) % 360.0
