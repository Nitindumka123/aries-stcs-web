import json
import os
import logging
import time
from astropy.time import Time
from src.drivers.mount.smart_serial import SmartSerial
from src.core.legacy_decoder import LegacyDecoder
from src.core.astrometry import AstrometryEngine

logger = logging.getLogger("MountCoordinator")

class MountCoordinator:
    """
    Manages RA, DEC, Dome. Handles persistent offsets for Incremental Encoders.
    Calculates derived astronomical parameters using AstrometryEngine.
    """
    DEC_INDEX_HOME_DEG = 29.0 + (49.0 / 60.0) + (59.9 / 3600.0)
    DEC_INDEX_RAW_COUNT = 0

    def __init__(self):
        self.ra_driver = None
        self.dec_driver = None
        self.dome_driver = None
        
        # Initialize Astrometry Engine
        self.astro = AstrometryEngine()
        
        # Load Config & State
        self.config = self._load_json('config/settings.json')
        self.state = self._load_json('config/state.json', default={'dec_offset': 0, 'dome_offset': 0})
        
        # Restore offsets from disk so we "remember" position across restarts
        self.dec_offset_counts = self.state.get('dec_offset', 0)
        self.dome_offset_counts = self.state.get('dome_offset', 0)
        
        # Restore persisted manual home value — this IS the DEC ground truth.
        # If no home has been set, fall back to +29:49:59.9
        FALLBACK_DEC_HOME = self.DEC_INDEX_HOME_DEG  # +29:49:59.9
        self.dec_home_deg = self.state.get('dec_home_deg', None)
        self.last_raw_dec = None
        self._dec_index_home_applied = False
        self.is_slewing = False  # Set by TelemetryWorker from MotionState; suppresses homing during slews
        
        # Dynamically set MOUNTING_DEC_ADJ from dec_home_deg.
        # This replaces the old hardcoded 115800" from aries1m.c.
        effective_home = self.dec_home_deg if self.dec_home_deg is not None else FALLBACK_DEC_HOME
        LegacyDecoder.MOUNTING_DEC_ADJ = effective_home * 3600.0
        
        # Restore persisted sync biases into LegacyDecoder
        LegacyDecoder.HRA_ENCODER_ZERO_BIAS_ARCSEC = float(self.state.get('hra_encoder_zero_bias_arcsec', 0.0))
        LegacyDecoder.minor_hra_adj = float(self.state.get('minor_hra_adj', 0.0))
        LegacyDecoder.minor_dec_adj = float(self.state.get('minor_dec_adj', 0.0))
        
        # Auto-Save Logic
        self.last_save_time = time.time()
        self.save_interval = 60.0 # Save state every 60 seconds
        
        logger.info(
            f"State Restored. Offsets -> DEC: {self.dec_offset_counts}, DOME: {self.dome_offset_counts}, "
            f"HRA_zero_bias: {LegacyDecoder.HRA_ENCODER_ZERO_BIAS_ARCSEC}, "
            f"HRA_adj: {LegacyDecoder.minor_hra_adj}, DEC_adj: {LegacyDecoder.minor_dec_adj}, "
            f"DEC_home: {self.dec_home_deg} (MOUNTING_DEC_ADJ={LegacyDecoder.MOUNTING_DEC_ADJ:.0f}\")" 
        )

    def _resolve_path(self, relative_path):
        """Finds file relative to project root (handles bundled EXE correctly)."""
        # Prioritize STCS_EXTERNAL_ROOT set in main.py
        base_path = os.environ.get('STCS_EXTERNAL_ROOT')
        if not base_path:
            # Fallback for dev mode if not called through main.py
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        
        path = os.path.join(base_path, relative_path)
        return path

    def _load_json(self, relative_path, default=None):
        try:
            path = self._resolve_path(relative_path)
            if not os.path.exists(path):
                return default if default is not None else {}
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {relative_path}: {e}")
            return default if default is not None else {}

    def _save_state(self):
        """Writes current offsets to config/state.json."""
        try:
            path = self._resolve_path('config/state.json')
            data = {
                'dec_offset': self.dec_offset_counts,
                'dome_offset': self.dome_offset_counts,
                'hra_encoder_zero_bias_arcsec': LegacyDecoder.HRA_ENCODER_ZERO_BIAS_ARCSEC,
                'minor_hra_adj': LegacyDecoder.minor_hra_adj,
                'minor_dec_adj': LegacyDecoder.minor_dec_adj,
                'dec_home_deg': self.dec_home_deg
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)
            self.last_save_time = time.time()
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def _effective_dec_home_deg(self):
        """Return the configured DEC index home, falling back to the legacy value."""
        return (
            float(self.dec_home_deg)
            if self.dec_home_deg is not None
            else self.DEC_INDEX_HOME_DEG
        )

    def _apply_dec_index_home(self, persist=False):
        """
        Treat raw DEC count 0 from the firmware as the DEC index-home edge.

        After the reset edge, the Arduino reports signed counts around zero.
        Count 0 displays as the configured dec_home_deg; positive counts move
        DEC north from that value and negative counts move DEC south.
        """
        old_home = self.dec_home_deg
        old_offset = self.dec_offset_counts
        home_deg = self._effective_dec_home_deg()

        if self.dec_home_deg is None:
            self.dec_home_deg = home_deg
        LegacyDecoder.MOUNTING_DEC_ADJ = home_deg * 3600.0
        self.dec_offset_counts = 0
        self._dec_index_home_applied = True

        if old_home != self.dec_home_deg or old_offset != self.dec_offset_counts:
            logger.info(
                f"DEC INDEX HOME APPLIED: raw=0 -> "
                f"{LegacyDecoder.decimal_deg_to_dms(home_deg)}, "
                f"offset {old_offset} -> {self.dec_offset_counts}"
            )

        if persist:
            self._save_state()

    def _dec_index_counts_to_degrees(self, counts):
        return self._effective_dec_home_deg() + (
            counts * LegacyDecoder.CO_DEC_ARCSEC_PER_COUNT / 3600.0
        )

    def connect_hardware(self):
        try:
            conns = self.config.get('connections', {})
            # RA
            ra_sn = conns.get('ra_controller', {}).get('serial_number')
            if ra_sn:
                self.ra_driver = SmartSerial(ra_sn)
                self.ra_driver.connect()
            # DEC
            dec_sn = conns.get('dec_controller', {}).get('serial_number')
            if dec_sn:
                self.dec_driver = SmartSerial(dec_sn)
                self.dec_driver.connect()
            # DOME
            dome_sn = conns.get('dome_controller', {}).get('serial_number')
            if dome_sn:
                self.dome_driver = SmartSerial(dome_sn)
                self.dome_driver.connect()
            return True
        except Exception as e:
            logger.error(f"Hardware Connection Failed: {e}")
            self.disconnect_hardware()
            raise e

    def disconnect_hardware(self):
        # Save one last time before disconnect
        self._save_state()
        if self.ra_driver: self.ra_driver.close()
        if self.dec_driver: self.dec_driver.close()
        if self.dome_driver: self.dome_driver.close()

    def sync_coordinates(self, target_dec_deg, target_dome_az):
        """
        Calibrates incremental encoders and SAVES the offset to disk.
        """
        raw_dec = 0
        raw_dome = 0
        
        if self.dec_driver and self.dec_driver.connection.is_open:
            resp = self.dec_driver.send_command("A'\n")
            if resp and resp.lstrip('-').isdigit(): raw_dec = int(resp)
                
        if self.dome_driver and self.dome_driver.connection.is_open:
            resp = self.dome_driver.send_command("A'\n")
            if resp and resp.lstrip('-').isdigit(): raw_dome = int(resp)

        expected_dec_counts = (target_dec_deg * 3600.0) / LegacyDecoder.CO_DEC_ARCSEC_PER_COUNT
        expected_dome_counts = target_dome_az / LegacyDecoder.CO_DOME_DEG_PER_COUNT

        self.dec_offset_counts = int(expected_dec_counts - raw_dec)
        self.dome_offset_counts = int(expected_dome_counts - raw_dome)
        self._dec_index_home_applied = False
        
        # SAVE TO DISK IMMEDIATELY
        self._save_state()
        
        logger.info(f"SYNC COMPLETE & SAVED. Offsets -> DEC: {self.dec_offset_counts}, DOME: {self.dome_offset_counts}")

    def set_dec_home(self, home_dec_deg):
        """
        Manual Homing: Sets the DEC encoder offset so that the current
        raw encoder reading maps to the specified home DEC value.

        This also updates MOUNTING_DEC_ADJ to match the new home,
        since dec_home_deg is the ground truth for the DEC zero reference.

        Pipeline after update:
          DEC° = ((raw + offset) × 0.9 + home_dec_deg × 3600 + minor_dec_adj) / 3600

        Since we just set MOUNTING_DEC_ADJ = home_dec_deg × 3600, and
        the telescope is AT the home position, the offset should make the
        raw reading produce exactly home_dec_deg.
        """
        raw_dec = 0

        if self.dec_driver and self.dec_driver.connection.is_open:
            resp = self.dec_driver.send_command("A'\n")
            if resp and resp.lstrip('-').isdigit():
                raw_dec = int(resp)
            else:
                raise RuntimeError("Failed to read raw DEC encoder count")
        else:
            raise RuntimeError("DEC Arduino not connected")

        # 1. Update the ground truth: MOUNTING_DEC_ADJ = new home
        old_mounting_adj = LegacyDecoder.MOUNTING_DEC_ADJ
        LegacyDecoder.MOUNTING_DEC_ADJ = home_dec_deg * 3600.0

        # 2. Recalculate offset with the NEW mounting adj.
        #    Target: (raw + offset) × 0.9 + new_MOUNTING_DEC_ADJ + minor_dec_adj = home_dec_deg × 3600
        #    Since new_MOUNTING_DEC_ADJ = home_dec_deg × 3600:
        #      (raw + offset) × 0.9 + minor_dec_adj = 0
        #      offset = (-minor_dec_adj / 0.9) - raw
        target_arcsec = home_dec_deg * 3600.0
        required_counts = (target_arcsec - LegacyDecoder.MOUNTING_DEC_ADJ - LegacyDecoder.minor_dec_adj) / LegacyDecoder.CO_DEC_ARCSEC_PER_COUNT
        offset = int(required_counts - raw_dec)

        logger.info(
            f"SET DEC HOME: dial={home_dec_deg:.4f}°, raw={raw_dec}, "
            f"old_offset={self.dec_offset_counts}, new_offset={offset}, "
            f"MOUNTING_DEC_ADJ: {old_mounting_adj:.0f}\" → {LegacyDecoder.MOUNTING_DEC_ADJ:.0f}\""
        )

        self.dec_offset_counts = offset
        self.dec_home_deg = home_dec_deg
        self._dec_index_home_applied = False

        # Persist immediately
        self._save_state()

        logger.info(f"DEC HOME SET & SAVED. Offset -> {self.dec_offset_counts}")

    def set_tracking(self, enabled=True):
        """
        Enables/Disables Tracking Mode on the RA Controller.
        """
        if not self.ra_driver: return
        
        # Based on aries1.c logic, we might need a specific command to enable tracking.
        # Often it is :MT# (Move Track) or setting a drive mode.
        # Since we don't have the exact command, we can try :MS# (Move Slew) to target?
        # Or maybe it just needs a "Target Speed".
        
        # For now, let's assume we can just log it, as we are in Phase B (Python Control).
        # To track, we need to continuously update the target HRA or set a velocity.
        if enabled:
            logger.info("Tracking ENABLED (Logic pending implementation)")
            # self.ra_driver.send_command(":MT#") 
        else:
            logger.info("Tracking DISABLED")
            # self.ra_driver.send_command(":Q#")

    def get_telemetry(self):
        effective_dec_home = self._effective_dec_home_deg()
        telemetry = {
            "ra_hms": "00:00:00",
            "dec_dms": "+00:00:00",
            "dome_az": 0.0,
            "raw_hra": 0,
            "raw_dec": 0,
            "raw_dec_encoder": 0,
            "dec_index_home_deg": effective_dec_home,
            "dec_index_home_active": False,
            # Derived astronomical values
            "hra_hms": "00:00:00",
            "lst_hms": "00:00:00",
            "az_deg": 0.0,
            "alt_deg": 0.0,
            "airmass": 1.0,
            "jd": 0.0,
            # Decimal values for downstream computation
            "hra_decimal": 0.0,
            "ra_decimal": 0.0,
            "dec_decimal": 0.0,
            "lst_decimal": 0.0
        }

        # The HRA encoder reads Hour Angle, NOT RA.
        # RA is derived as: RA = LST - HRA (aries1m.c line 3652)
        current_hra_hours = 0.0
        current_ra_hours = 0.0
        current_dec_deg = 0.0

        try:
            # --- HRA Controller (26-bit A90 Absolute Encoder) ---
            # Reads Hour Angle directly. RA is derived later from LST.
            # aries1m.c: enc_HRA_enquiry() -> "R'\n" -> Encoder_26bit_A90_ABS_HRA_read()
            if self.ra_driver and self.ra_driver.connection.is_open:
                try:
                    raw = self.ra_driver.send_command("R'\n")
                    if raw and raw.isdigit():
                        counts = int(raw)
                        telemetry['raw_hra'] = counts

                        # Convert raw counts -> HRA hours (with mounting + minor biases)
                        current_hra_hours = LegacyDecoder.counts_to_hra_hours(counts)
                except Exception as e:
                    logger.error(f"Error reading HRA: {e}")
                    self._save_state()

            # --- DEC Controller (1000 PPR Incremental Encoder) ---
            # aries1m.c: enc_dec_enquiry_PPR_AB_incremental() -> "A'\n"
            if self.dec_driver and self.dec_driver.connection.is_open:
                try:
                    raw = self.dec_driver.send_command("A'\n")
                    if raw and raw.lstrip('-').isdigit():
                        counts = int(raw)
                        
                        # -- DEC Index Homing Detection --
                        # Latest firmware resets encoderPos to exactly 0 only on
                        # the accepted north/index edge. Use that explicit value
                        # as the home marker instead of inferring a large jump.
                        index_edge_seen = (
                            counts == self.DEC_INDEX_RAW_COUNT
                            and self.last_raw_dec != self.DEC_INDEX_RAW_COUNT
                        )
                        if counts == self.DEC_INDEX_RAW_COUNT and (
                            index_edge_seen or not self._dec_index_home_applied
                        ):
                            logger.info(
                                f"DEC index reset detected: raw DEC {self.last_raw_dec} -> {counts}. "
                                f"Displaying {LegacyDecoder.decimal_deg_to_dms(self._effective_dec_home_deg())}"
                            )
                            self._apply_dec_index_home(persist=index_edge_seen)

                        self.last_raw_dec = counts

                        # Apply persistent offset until the firmware index home
                        # is seen. After that, signed raw counts are relative
                        # to the configured DEC home by definition.
                        if self._dec_index_home_applied:
                            corrected_counts = counts
                            current_dec_deg = self._dec_index_counts_to_degrees(counts)
                        else:
                            corrected_counts = counts + self.dec_offset_counts
                            current_dec_deg = LegacyDecoder.counts_to_dec_degrees(corrected_counts)

                        telemetry['raw_dec'] = corrected_counts
                        telemetry['raw_dec_encoder'] = counts
                        telemetry['dec_index_home_deg'] = self._effective_dec_home_deg()
                        telemetry['dec_index_home_active'] = (
                            self._dec_index_home_applied
                            and counts == self.DEC_INDEX_RAW_COUNT
                        )
                        telemetry['dec_dms'] = LegacyDecoder.decimal_deg_to_dms(current_dec_deg)
                except Exception as e:
                    logger.error(f"Error reading DEC: {e}")
                    self._save_state()

            # --- DOME Controller (100 PPR Incremental Encoder) ---
            # aries1m.c: enc_dome_enquiry() -> "A'\n"
            if self.dome_driver and self.dome_driver.connection.is_open:
                try:
                    raw = self.dome_driver.send_command("A'\n")
                    if raw and raw.lstrip('-').isdigit():
                        counts = int(raw)
                        corrected_counts = counts + self.dome_offset_counts
                        telemetry['dome_az'] = LegacyDecoder.counts_to_dome_azimuth(corrected_counts)
                except Exception as e:
                    logger.error(f"Error reading DOME: {e}")
                    self._save_state()

            # --- Derive RA from LST & HRA, then compute AZ/EL/AirMass ---
            # This matches the aries1m.c pipeline:
            #   1. Read HRA from encoder (done above)
            #   2. Get LST from Astropy (replaces C polynomial)
            #   3. RA = LST - HRA (C line 3652)
            #   4. AZ/EL from Astropy (replaces C spherical trig)
            try:
                # 1. Get Current LST via Astropy (more accurate than C polynomial)
                lst_hours = self.astro.get_current_lst_hours()

                # 2. Derive RA = LST - HRA (aries1m.c line 3652)
                current_ra_hours = LegacyDecoder.hra_to_ra_hours(current_hra_hours, lst_hours)

                # 3. Format display strings
                telemetry['hra_hms'] = LegacyDecoder.decimal_hours_to_hms(current_hra_hours)
                telemetry['ra_hms'] = LegacyDecoder.decimal_hours_to_hms(current_ra_hours)
                telemetry['lst_hms'] = LegacyDecoder.decimal_hours_to_hms(lst_hours)

                # 4. Store decimal values for downstream computation
                telemetry['hra_decimal'] = current_hra_hours
                telemetry['ra_decimal'] = current_ra_hours
                telemetry['dec_decimal'] = current_dec_deg
                telemetry['lst_decimal'] = lst_hours

                # 5. Calculate AZ/EL/AirMass via Astropy (more accurate than C manual trig)
                # Clamp DEC to valid astronomical range before Astropy transforms.
                # The incremental DEC encoder can accumulate spurious counts from
                # motor relay transients, briefly producing values outside [-90, 90].
                safe_dec = max(-90.0, min(90.0, current_dec_deg))
                astro_data = self.astro.calculate_parameters(current_ra_hours, safe_dec)

                telemetry['az_deg'] = astro_data['az_deg']
                telemetry['alt_deg'] = astro_data['alt_deg']
                telemetry['airmass'] = astro_data['airmass']
                telemetry['jd'] = astro_data['jd']

            except Exception as e:
                logger.error(f"Astrometry Calculation Error: {e}")

            # Periodic Auto-Save (Every 60s)
            if time.time() - self.last_save_time > self.save_interval:
                self._save_state()

        except Exception as e:
            logger.critical(f"Critical Telemetry Failure: {e}")
            self._save_state()

        return telemetry
