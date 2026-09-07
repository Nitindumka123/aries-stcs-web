import math

class LegacyDecoder:
    """
    Port of the math logic from 'aries1m.c' to convert raw encoder counts
    into astronomical coordinates.

    Key change log (aligned with aries1m.c dated 01-Apr-2026):
    - HRA encoder reads Hour Angle, NOT RA. RA is derived as LST - HRA.
    - HRA: arcsec / 3600.0 gives hours (C line 3648), NOT arcsec / 54000.
    - Mounting biases applied: HRA = -2100 arcsec, DEC = +115800 arcsec.
    - Dome constant updated to 0.010578590109018248 from 21-May-2026 Z-pulse test.
    """

    # --- ENCODER CONSTANTS FROM aries1m.c ---

    # C line 992: #define co26bit1000 1.2874603271484375
    # HRA 26-bit A90 absolute encoder: (count * this / 1000) = arcseconds (time-seconds actually)
    # Math: 86400 time-seconds in a circle / 67108864 counts * 1000 = 1.2874603271484375
    CO_HRA_ARCSEC_PER_1000_COUNTS = 1.2874603271484375 # Updated from 1.2874603271484375 based on 25-May-2026 calibration.

    # C line 3660: dec_arcsec = (dec_inc_count * 0.9);
    # DEC 1000 PPR incremental encoder: 4000 counts/rev, 3600/4000 = 0.9 arcsec/count
    CO_DEC_ARCSEC_PER_COUNT = 0.900

    # Dome 100 PPR incremental encoder (recalibrated 21-May-2026).
    # Measured Z-pulse counts for one physical revolution:
    #   CW:  +34040 counts
    #   CCW: -34022 counts
    # Average counts/rev = 34031, so 360 / 34031 = 0.010578590109018248 deg/count.
    CO_DOME_DEG_PER_COUNT = 0.010578590109018248

    # --- MOUNTING BIASES FROM aries1m.c (arcseconds) ---
    # These are hardware-specific offsets set during telescope installation.
    # They align the encoder zero-point with the true celestial reference.

    # C line 781: double Mounting_hra_adj = -2100;
    MOUNTING_HRA_ADJ = -2100.0  # arcseconds

    # Site-requested fixed HA bias: +2 minutes of hour angle.
    # The HRA pipeline uses time-arcseconds, so 2 minutes = 120 seconds.
    HOUR_ANGLE_BIAS_ARCSEC = 120.0
    # HOUR_ANGLE_BIAS_ARCSEC = 0

    # Persistent encoder zero/home calibration. This aligns the physical HRA
    # zero position without consuming the observation-time minor_hra_adj offset.
    HRA_ENCODER_ZERO_BIAS_ARCSEC = 0.0

    # C line 781: double Mounting_dec_adj = 115800;
    # Originally 115800" from aries1m.c (+32.1667°) — calibrated for the C code installation.
    # Now dynamically set to dec_home_deg × 3600 from state.json by MountCoordinator.
    # Default fallback: +29:21:00 (29.35°) = ARIES Nainital telescope home.
    # MOUNTING_DEC_ADJ = 105660.0  # arcseconds (= +29.35 degrees, fallback)
    MOUNTING_DEC_ADJ = 0  # arcseconds (= +29.35 degrees, fallback)
    

    # C line 786: double Minor_hra_adj = 0, Minor_dec_adj = 0;
    # Runtime fine-tuning biases (set via sky catalog sync ':CM#' command).
    # These start at 0 and are adjusted during observation sessions.
    minor_hra_adj = 0.0  # arcseconds (instance-level, adjustable at runtime)
    minor_dec_adj = 0.0  # arcseconds (instance-level, adjustable at runtime)

    @staticmethod
    def counts_to_hra_hours(raw_counts):
        """
        Converts HRA Encoder counts to Hour Angle (decimal hours).

        Pipeline (from aries1m.c lines 3645-3650):
          1. hra_arcsec = (HRA_enc_count * co26bit1000) / 1000
          2. hra_arcsec += Mounting_hra_adj + fixed HA bias + encoder zero bias + Minor_hra_adj
          3. rhra_hours = hra_arcsec / 3600.0
          4. Normalize to 0-24h
        """
        # Step 1: Raw counts to arcseconds
        hra_arcsec = (raw_counts * LegacyDecoder.CO_HRA_ARCSEC_PER_1000_COUNTS) / 1000.0

        # Step 2: Apply mounting bias + fixed HA bias + runtime bias
        hra_arcsec += LegacyDecoder.MOUNTING_HRA_ADJ
        hra_arcsec += LegacyDecoder.HOUR_ANGLE_BIAS_ARCSEC
        hra_arcsec += LegacyDecoder.HRA_ENCODER_ZERO_BIAS_ARCSEC
        hra_arcsec += LegacyDecoder.minor_hra_adj

        # Step 3: Arcseconds to hours
        # In the C code (line 3648): rhra_hours = hra_arcsec / 3600.0
        # The encoder calibration constant maps the full encoder range to 24 hours,
        # so dividing arcsec by 3600 directly yields hours.
        hra_hours = hra_arcsec / 3600.0

        # Step 4: Normalize to 0-24 range
        return hra_hours % 24.0

    @staticmethod
    def hra_to_ra_hours(hra_hours, lst_hours):
        """
        Derives RA from HRA and LST.

        From aries1m.c lines 3652-3654:
          rra_hours = rlst_hours - rhra_hours;
          if (rra_hours < 0) rra_hours += 24.0;
          else if (rra_hours > 24) rra_hours -= 24.0;
        """
        return (lst_hours - hra_hours) % 24.0

    @staticmethod
    def counts_to_dec_degrees(raw_counts):
        """
        Converts DEC Encoder counts to Degrees.

        Pipeline (from aries1m.c lines 3660-3666):
          1. dec_arcsec = dec_inc_count * 0.9
          2. dec_arcsec += Mounting_dec_adj + Minor_dec_adj
          3. rdec_deg = dec_arcsec / 3600.0
        """
        # Step 1: Raw counts to arcseconds
        dec_arcsec = raw_counts * LegacyDecoder.CO_DEC_ARCSEC_PER_COUNT

        # Step 2: Apply mounting bias + runtime bias
        dec_arcsec += LegacyDecoder.MOUNTING_DEC_ADJ
        dec_arcsec += LegacyDecoder.minor_dec_adj

        # Step 3: Arcseconds to degrees
        dec_degrees = dec_arcsec / 3600.0

        return dec_degrees

    @staticmethod
    def counts_to_dome_azimuth(raw_counts):
        """
        Converts Dome Encoder counts to Azimuth (0-360).

        Uses the measured Z-pulse span of 34031 counts per revolution.
        """
        azimuth = raw_counts * LegacyDecoder.CO_DOME_DEG_PER_COUNT

        return azimuth % 360.0

    @staticmethod
    def reset_minor_biases():
        """
        Resets runtime fine-tuning biases to zero.
        Equivalent to aries1m.c local_bias_reset_Ra_Dec() (line 3158).
        """
        LegacyDecoder.minor_hra_adj = 0.0
        LegacyDecoder.minor_dec_adj = 0.0

    @staticmethod
    def apply_sync_bias(ra_current, ra_target, dec_current, dec_target):
        """
        Applies a sky catalog sync correction (equivalent to ':CM#' command).
        From aries1m.c lines 3347-3356:
          Minor_hra_adj += (int)((rra_hours - sky_ra_req) * 54000.0)
          Minor_dec_adj += (int)((sky_dec_req - rdec_deg) * 3600.0)
        Safety: biases are clamped to ±7200 arcsec (±2° / ±8min).
        """
        import logging
        _logger = logging.getLogger("LegacyDecoder")

        ra_error_hours = (ra_current - ra_target + 12.0) % 24.0 - 12.0
        hra_correction = int(round(ra_error_hours * 3600.0))
        dec_correction = int((dec_target - dec_current) * 3600.0)

        LegacyDecoder.minor_hra_adj += hra_correction
        LegacyDecoder.minor_dec_adj += dec_correction

        # Safety clamp — cap at limit rather than resetting to 0
        MAX_BIAS = 7200  # ±2 degrees
        if abs(LegacyDecoder.minor_hra_adj) > MAX_BIAS:
            _logger.warning(f"HRA bias {LegacyDecoder.minor_hra_adj} exceeds ±{MAX_BIAS}\", clamping.")
            LegacyDecoder.minor_hra_adj = max(-MAX_BIAS, min(MAX_BIAS, LegacyDecoder.minor_hra_adj))
        if abs(LegacyDecoder.minor_dec_adj) > MAX_BIAS:
            _logger.warning(f"DEC bias {LegacyDecoder.minor_dec_adj} exceeds ±{MAX_BIAS}\", clamping.")
            LegacyDecoder.minor_dec_adj = max(-MAX_BIAS, min(MAX_BIAS, LegacyDecoder.minor_dec_adj))

    @staticmethod
    def decimal_hours_to_hms(decimal_hours):
        """
        Utility to convert 5.5 hours -> "05:30:00.0" string.
        """
        sign = "-" if decimal_hours < 0 else ""
        abs_h = abs(decimal_hours)
        h = int(abs_h)
        m = int((abs_h - h) * 60)
        s = (abs_h - h - m/60) * 3600
        return f"{sign}{h:02d}:{m:02d}:{s:04.1f}"

    @staticmethod
    def decimal_deg_to_dms(decimal_deg):
        """
        Utility to convert 45.5 degrees -> "+45:30:00.0" string.
        """
        sign = "+" if decimal_deg >= 0 else "-"
        abs_d = abs(decimal_deg)
        d = int(abs_d)
        m = int((abs_d - d) * 60)
        s = (abs_d - d - m/60) * 3600
        return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"
