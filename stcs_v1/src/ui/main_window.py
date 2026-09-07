import os
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QGroupBox, QGridLayout,
                             QStatusBar, QMessageBox, QMenuBar, QApplication)
from PyQt6.QtCore import pyqtSlot, Qt, QTimer
from PyQt6.QtGui import QAction

# Workers
from src.workers.telemetry_worker import TelemetryWorker
from src.workers.weather_worker import WeatherWorker
from src.workers.camera_worker import CameraWorker
from src.workers.gps_worker import GPSWorker
from src.workers.alpaca_server import AlpacaServerThread
from src.workers.telemetry_server import TelemetryServerThread

# Drivers
from src.drivers.camera.science_driver import ScienceCameraDriver
from src.drivers.mount.control_serial import ControlSerial

# Core
from src.core.motion_state import MotionState
from src.core.simulation_engine import SimulationEngine
from src.core.slew_engine import SlewEngine
from src.core.astrometry import AstrometryEngine
from src.core.legacy_decoder import LegacyDecoder
from src.core.dome_sync import DomeSyncWorker
from src.core.dome_geometry import corrected_dome_azimuth
from src.core.safety import AltitudeSafetyGuard

# Components
from src.ui.components.motion_panel import MotionPanel
from src.ui.windows.camera_window import CameraControlWindow
from src.ui.windows.all_sky_window import AllSkyWindow
from src.ui.windows.gps_window import GPSMonitorWindow

logger = logging.getLogger("MainWindow")

IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="IST")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("104 cm Sampurnanand Telescope Control System")
        self.setMinimumSize(800, 600)
        self.resize(1100, 750)

        # ─── CORE STATE ────────────────────────────────────────
        self.motion_state = MotionState()
        self.astro = AstrometryEngine()
        self.altitude_guard = AltitudeSafetyGuard(self.astro)
        self.slew_engine = SlewEngine(self.motion_state, self.astro)
        
        self.dome_sync_worker = None
        self.auto_sync_active = False
        self._gps_connected = False
        self._gps_status_message = "Auto-discovering..."
        self._gps_time_utc = None
        self._gps_time_monotonic = None
        self._last_gps_utc_dt = None
        self._last_gps_position = None
        self._last_altitude_alert_at = 0.0
        self._last_altitude_alert_message = ""
        self._invalid_telemetry_count = 0

        # ─── CONTROL ARDUINO (DUO Mega 2560) ───────────────────
        self.control_serial = None  # Initialized on connect

        # ─── DRIVERS & WORKERS ─────────────────────────────────
        # 1. Science Camera
        self.science_driver = ScienceCameraDriver()
        self.camera_worker = CameraWorker(self.science_driver)
        self.camera_worker.start()

        # 2. Telemetry (Mount Encoders)
        self.telemetry_worker = TelemetryWorker()
        self.telemetry_worker.motion_state = self.motion_state  # Feed slewing state for Z-pulse homing
        self.telemetry_worker.telemetry_updated.connect(self.update_telemetry)
        self.telemetry_worker.connection_status.connect(self.handle_connection_status)
        self.telemetry_worker.log_message.connect(self.handle_log)

        # 3. Weather
        self.weather_worker = WeatherWorker()
        self.weather_worker.weather_updated.connect(self.update_weather)
        self.weather_worker.safety_alert.connect(self.handle_safety_alert)
        self.weather_worker.start()

        # 4. GPS
        self.gps_worker = GPSWorker(port="AUTO")
        self.gps_worker.gps_data_updated.connect(self.feed_gps_to_astrometry)
        self.gps_worker.connection_status.connect(self.handle_gps_status)
        self.gps_worker.start()

        # 5. Simulation Engine (only in SIMULATION mode)
        self.sim_engine = None
        if self.motion_state.mode == "SIMULATION":
            self.sim_engine = SimulationEngine(self.motion_state)
            self.sim_engine.start()

        # 6. Alpaca Server for Cartes du Ciel
        self.alpaca_thread = AlpacaServerThread(
            self.motion_state, self.slew_engine, self.astro
        )
        self.alpaca_thread.start()
        logger.info("Alpaca server thread started.")

        # 7. WebSocket Telemetry Server for Mobile Remote Control
        self.telemetry_server = TelemetryServerThread(
            self.motion_state, self.slew_engine, self.astro
        )
        self.telemetry_server.start()
        logger.info("WebSocket telemetry server thread started.")

        # ─── SUB-WINDOWS ───────────────────────────────────────
        self.camera_window = CameraControlWindow(self.camera_worker)
        self.all_sky_window = AllSkyWindow()
        self.gps_window = GPSMonitorWindow()

        self.gps_worker.gps_data_updated.connect(self.gps_window.update_ui)
        self.gps_worker.connection_status.connect(self.gps_window.handle_connection)

        # ─── UI BUILD ──────────────────────────────────────────
        self.init_menu_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        self.init_header()
        self.init_dashboard()
        self.init_raw_panel()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.camera_worker.status_message.connect(self.status_bar.showMessage)

        # ─── 10Hz CONTROL LOOP ─────────────────────────────────
        self.control_timer = QTimer()
        self.control_timer.timeout.connect(self._control_loop_tick)
        self.control_timer.start(100)  # 10Hz

        # ─── 1Hz SLOW UI LOOP  ─────────────────────────────────
        self.slow_timer = QTimer()
        self.slow_timer.timeout.connect(self._slow_loop_tick)
        self.slow_timer.start(1000)  # 1Hz

        # ─── COOLDOWN TIMER ────────────────────────────────────
        self.cooldown_timer = QTimer()
        self.cooldown_timer.timeout.connect(self._cooldown_tick)
        self.cooldown_ticks = 0

    # ═══════════════════════════════════════════════════════════
    # MENU BAR (Windows for Camera / AllSky / GPS)
    # ═══════════════════════════════════════════════════════════
    def init_menu_bar(self):
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet(
            "QMenuBar { background-color: #1a1a2e; color: #ddd; font-size: 13px; "
            "border-bottom: 1px solid #333; padding: 2px; }"
            "QMenuBar::item { padding: 6px 14px; border-radius: 3px; }"
            "QMenuBar::item:selected { background-color: #333; }"
            "QMenu { background-color: #1e1e2e; color: #ddd; border: 1px solid #444; padding: 4px; }"
            "QMenu::item { padding: 6px 24px; }"
            "QMenu::item:selected { background-color: #0288d1; color: white; }"
        )

        # ── Windows menu ──
        windows_menu = menu_bar.addMenu("Windows")

        act_camera = QAction("📷  Science Camera", self)
        act_camera.triggered.connect(self.open_camera_window)
        windows_menu.addAction(act_camera)

        act_allsky = QAction("☁  All Sky Cam", self)
        act_allsky.triggered.connect(self.open_all_sky_window)
        windows_menu.addAction(act_allsky)

        act_gps = QAction("📡  GPS Monitor", self)
        act_gps.triggered.connect(self.open_gps_window)
        windows_menu.addAction(act_gps)

        # ── View menu (raw encoder toggle) ──
        view_menu = menu_bar.addMenu("View")

        self.act_toggle_raw = QAction("Show Raw Encoder Telemetry", self)
        self.act_toggle_raw.setCheckable(True)
        self.act_toggle_raw.setChecked(False)
        self.act_toggle_raw.triggered.connect(self._toggle_raw_panel)
        view_menu.addAction(self.act_toggle_raw)

    # ═══════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════
    def init_header(self):
        header_group = QGroupBox("System Connection")
        header_layout = QHBoxLayout()

        self.btn_connect = QPushButton("CONNECT TELESCOPE")
        self.btn_connect.setCheckable(True)
        self.btn_connect.clicked.connect(self.toggle_connection)
        self.btn_connect.setMinimumWidth(150)
        self.btn_connect.setStyleSheet("font-weight: bold; padding: 4px;")
        header_layout.addWidget(self.btn_connect)

        self.status_indicators = {}
        for name in ["RA", "DEC", "DOME", "CTRL"]:
            lbl = QLabel(f"{name}: OFFLINE")
            lbl.setStyleSheet(
                "color: #ff4444; font-weight: bold; border: 1px solid #333; "
                "padding: 5px; background-color: #111; border-radius: 4px;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(lbl)
            self.status_indicators[name] = lbl

        # Mode indicator
        mode_lbl = QLabel(f"MODE: {self.motion_state.mode}")
        mode_color = "#66bb6a" if self.motion_state.mode == "SIMULATION" else "#42a5f5"
        mode_lbl.setStyleSheet(
            f"color: {mode_color}; font-weight: bold; border: 1px solid #333; "
            "padding: 5px; background-color: #111; border-radius: 4px;"
        )
        mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(mode_lbl)

        # Alpaca indicator
        alpaca_lbl = QLabel("ALPACA: ACTIVE")
        alpaca_lbl.setStyleSheet(
            "color: #ab47bc; font-weight: bold; border: 1px solid #333; "
            "padding: 5px; background-color: #111; border-radius: 4px;"
        )
        alpaca_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(alpaca_lbl)

        self.lbl_gps_status = QLabel("GPS: SEARCHING")
        self.lbl_gps_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.lbl_gps_status)
        self._update_gps_status_label()

        self.lbl_ist_time = QLabel("IST: --:--:-- (SYSTEM)")
        self.lbl_ist_time.setStyleSheet(
            "color: #00ffcc; font-weight: bold; border: 1px solid #333; "
            "padding: 5px; background-color: #111; border-radius: 4px;"
        )
        self.lbl_ist_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.lbl_ist_time)
        self._update_ist_display()

        header_layout.addStretch()
        header_group.setLayout(header_layout)
        self.main_layout.addWidget(header_group)

    # ═══════════════════════════════════════════════════════════
    # DASHBOARD
    # ═══════════════════════════════════════════════════════════
    def init_dashboard(self):
        dashboard_layout = QHBoxLayout()

        # --- LEFT: TELEMETRY ---
        left_panel = QGroupBox("Mount Telemetry")
        left_layout = QVBoxLayout()

        grid_coords = QGridLayout()
        self.lcd_ra = self.create_lcd_display("00:00:00")
        grid_coords.addWidget(QLabel("RIGHT ASCENSION (RA)"), 0, 0)
        grid_coords.addWidget(self.lcd_ra, 1, 0)

        self.lcd_hra = self.create_lcd_display("00:00:00", color="#eab308")
        grid_coords.addWidget(QLabel("HOUR ANGLE (HRA)"), 2, 0)
        grid_coords.addWidget(self.lcd_hra, 3, 0)

        grid_coords.addWidget(QLabel("DECLINATION (DEC)"), 4, 0)
        dec_split_widget = QWidget()
        dec_split_layout = QHBoxLayout(dec_split_widget)
        dec_split_layout.setContentsMargins(0, 0, 0, 0)
        dec_split_layout.setSpacing(5)
        self.lcd_dec_deg = self.create_lcd_display("+00")
        self.lcd_dec_min = self.create_lcd_display("00")
        self.lcd_dec_sec = self.create_lcd_display("00.0")
        dec_split_layout.addWidget(self.lcd_dec_deg)
        dec_split_layout.addWidget(self.lcd_dec_min)
        dec_split_layout.addWidget(self.lcd_dec_sec)
        grid_coords.addWidget(dec_split_widget, 5, 0)

        # Azimuth and Altitude
        self.lcd_az = self.create_lcd_display("000.0°")
        grid_coords.addWidget(QLabel("AZIMUTH (AZ)"), 6, 0)
        grid_coords.addWidget(self.lcd_az, 7, 0)

        self.lcd_alt = self.create_lcd_display("+00.0°")
        grid_coords.addWidget(QLabel("ALTITUDE (ALT)"), 8, 0)
        grid_coords.addWidget(self.lcd_alt, 9, 0)

        # Motor status label — fixed width prevents panel from shifting when text changes
        self.lbl_motor_status = QLabel("Motors: IDLE")
        self.lbl_motor_status.setStyleSheet(
            "font-family: 'Consolas', monospace; font-size: 13px; color: #888; "
            "background: #0a0a0a; border: 1px solid #333; padding: 4px; border-radius: 3px;"
        )
        self.lbl_motor_status.setMinimumWidth(320)
        self.lbl_motor_status.setWordWrap(False)
        self.lbl_motor_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid_coords.addWidget(self.lbl_motor_status, 10, 0)

        # LST and JD display (moved from header)
        self.lbl_lst = self.create_lcd_display("00:00:00", color="#4488ff", size=22)
        grid_coords.addWidget(QLabel("LOCAL SIDEREAL TIME (LST)"), 11, 0)
        grid_coords.addWidget(self.lbl_lst, 12, 0)

        self.lbl_jd = self.create_lcd_display("0000000.00000", color="#4488ff", size=22)
        grid_coords.addWidget(QLabel("JULIAN DATE (JD)"), 13, 0)
        grid_coords.addWidget(self.lbl_jd, 14, 0)

        left_layout.addLayout(grid_coords)
        left_layout.addStretch()
        left_panel.setLayout(left_layout)
        dashboard_layout.addWidget(left_panel, 1)

        # --- CENTER: COMMAND DECK ---
        center_panel = QGroupBox("Command Deck")
        center_layout = QVBoxLayout()

        # Motion Control (direct embed — no tab wrapper)
        self.motion_panel = MotionPanel(worker=self.telemetry_worker)
        self._wire_motion_signals()
        self._update_offset_status_label()  # Show persisted offsets on startup
        self._init_dec_home_status()        # Show persisted home status on startup

        center_layout.addWidget(self.motion_panel)
        center_panel.setLayout(center_layout)
        dashboard_layout.addWidget(center_panel, 2)

        # --- RIGHT: ENVIRONMENT ---
        right_panel = QGroupBox("Environment")
        right_layout = QVBoxLayout()
        self.lcd_dome = self.create_lcd_display("000.0°", color="#4488ff")
        right_layout.addWidget(QLabel("DOME AZIMUTH"))
        right_layout.addWidget(self.lcd_dome)

        # Sync Buttons
        sync_btn_layout = QHBoxLayout()
        self.btn_dome_sync = QPushButton("🔄 SYNC")
        self.btn_dome_sync.setStyleSheet("background-color: #00838f; color: white; font-weight: bold; border-radius: 4px; padding: 6px;")
        self.btn_dome_sync.clicked.connect(self._handle_dome_sync_request)
        sync_btn_layout.addWidget(self.btn_dome_sync)

        self.btn_auto_track_sync = QPushButton("🤖 AUTO TRACK SYNC")
        self.btn_auto_track_sync.setCheckable(True)
        self.btn_auto_track_sync.setStyleSheet(
            "QPushButton { background-color: #1a1a2e; color: #8888aa; border: 1px solid #333; border-radius: 4px; padding: 6px; font-weight: bold;}"
            "QPushButton:checked { background-color: #1a237e; color: #82b1ff; border: 2px solid #5c6bc0; }"
        )
        self.btn_auto_track_sync.toggled.connect(self._toggle_auto_track_sync)
        sync_btn_layout.addWidget(self.btn_auto_track_sync)
        
        right_layout.addLayout(sync_btn_layout)

        self.lbl_airmass = self.create_lcd_display("--", color="#eab308", size=22)
        right_layout.addWidget(QLabel("AIRMASS"))
        right_layout.addWidget(self.lbl_airmass)

        self.val_temp = QLabel("-- C")
        self.val_humidity = QLabel("-- %")
        self.val_gps_lat = QLabel("Latitude: --")
        self.val_gps_lon = QLabel("Longitude: --")
        self.val_gps_alt = QLabel("Altitude: --")
        right_layout.addWidget(QLabel("Temperature:"))
        right_layout.addWidget(self.val_temp)
        right_layout.addWidget(QLabel("Humidity:"))
        right_layout.addWidget(self.val_humidity)
        right_layout.addWidget(QLabel("GPS Position:"))
        right_layout.addWidget(self.val_gps_lat)
        right_layout.addWidget(self.val_gps_lon)
        right_layout.addWidget(self.val_gps_alt)

        right_layout.addStretch()
        right_panel.setLayout(right_layout)
        dashboard_layout.addWidget(right_panel, 1)

        self.main_layout.addLayout(dashboard_layout)

    def init_raw_panel(self):
        self.raw_group = QGroupBox("Raw Encoder Telemetry")
        raw_layout = QHBoxLayout()
        self.lbl_raw_ra = QLabel("HRA: 0")
        self.lbl_raw_ra.setObjectName("RawLabel")
        self.lbl_raw_dec = QLabel("DEC: 0")
        self.lbl_raw_dec.setObjectName("RawLabel")
        self.lbl_raw_dome = QLabel("DOME: 0")
        self.lbl_raw_dome.setObjectName("RawLabel")
        raw_layout.addWidget(self.lbl_raw_ra)
        raw_layout.addWidget(self.lbl_raw_dec)
        raw_layout.addWidget(self.lbl_raw_dome)
        self.raw_group.setLayout(raw_layout)
        self.raw_group.setVisible(False)  # Hidden by default
        self.main_layout.addWidget(self.raw_group)

    def _toggle_raw_panel(self, checked):
        """Toggle visibility of the Raw Encoder Telemetry panel."""
        self.raw_group.setVisible(checked)
        self.act_toggle_raw.setText(
            "Hide Raw Encoder Telemetry" if checked else "Show Raw Encoder Telemetry"
        )

    def create_lcd_display(self, text, color="#ff4444", size=28):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: {size}px; color: {color}; background: #000; "
            "border: 2px solid #333; padding: 5px; "
            "font-family: 'Orbitron', 'Consolas', monospace; border-radius: 4px;"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    # ═══════════════════════════════════════════════════════════
    # MOTION SIGNAL WIRING
    # ═══════════════════════════════════════════════════════════
    def _wire_motion_signals(self):
        """Wire MotionPanel signals to MotionState setters."""
        mp = self.motion_panel

        # Speed selectors
        mp.ra_speed_changed.connect(self.motion_state.set_ra_speed)
        mp.dec_speed_changed.connect(self.motion_state.set_dec_speed)

        # Direction (hold-to-move)
        mp.ra_direction_changed.connect(self.motion_state.set_ra_direction)
        mp.dec_direction_changed.connect(self.motion_state.set_dec_direction)

        # Tracking (one-shot pulse)
        mp.track_on_requested.connect(self.motion_state.activate_tracking)
        mp.track_off_requested.connect(self.motion_state.deactivate_tracking)

        # Dome (one-shot pulse)
        mp.dome_cw_requested.connect(lambda: self._handle_manual_dome_move("CW"))
        mp.dome_ccw_requested.connect(lambda: self._handle_manual_dome_move("CCW"))
        mp.dome_off_requested.connect(lambda: self._handle_manual_dome_move("OFF"))

        # Slew / Stop / Offset
        mp.slew_requested.connect(self._handle_slew_request)
        mp.stop_requested.connect(self._handle_stop_request)
        mp.park_requested.connect(self._handle_park_request)
        mp.set_ra_offset_requested.connect(self._handle_set_ra_offset)
        mp.set_dec_offset_requested.connect(self._handle_set_dec_offset)
        mp.set_dome_offset_requested.connect(self._handle_set_dome_offset)
        mp.clear_offsets_requested.connect(self._handle_clear_offsets)

        # Manual DEC homing
        mp.set_dec_home_requested.connect(self._handle_set_dec_home)

    # ═══════════════════════════════════════════════════════════
    # 10Hz CONTROL LOOP
    # ═══════════════════════════════════════════════════════════
    def _control_loop_tick(self):
        """
        Main control loop at 10Hz:
        1. Update slew engine (if slewing)
        2. Update fast UI elements (Coordinates)
        3. Build relay payload from MotionState
        4. Send to DUO Arduino (if connected)
        5. Check cooldown requests
        """
        # 1. Drive the slew engine
        slew_msg = self.slew_engine.update()
        if slew_msg:
            self.status_bar.showMessage(slew_msg)

        # 2. Update fast display (Smooth RA/DEC/HRA)
        if self.motion_state.mode == "SIMULATION":
            self._update_display_fast()

        # 3. Update IST at 10Hz so the tenths digit visibly ticks
        self._update_ist_display()

        # 4. Enforce altitude safety before any relay output is built.
        self._enforce_altitude_motion_limit()

        # 5. Build and send relay packet
        payload = self.motion_state.build_relay_payload()
        if self.control_serial and self.control_serial.connected:
            self.control_serial.send_relay_packet(payload)

        # 6. Update motor status at 10Hz so button presses show immediately
        self._update_motor_status()

        # 7. Check cooldown
        if self.motion_state.request_cooldown:
            self.motion_state.request_cooldown = False
            self._start_cooldown()

    def _slow_loop_tick(self):
        """
        Slow UI update loop at 1Hz:
        1. Update expensive astrometry (both modes)
        2. Update motion panel visual state
        3. Check Auto Track Sync
        """
        # 1. Update expensive astrometry (Astropy SkyCoord transforms)
        if self.motion_state.mode == "SIMULATION":
            self._update_astro_slow()
        # In REAL mode, astrometry is updated via update_telemetry() signal
        # from TelemetryWorker whenever new data arrives.

        # 2. Update motion panel visual state at 1Hz (checkboxes, speed selectors)
        status = self.motion_state.get_status_snapshot()
        self.motion_panel.update_from_state(status)
        
        # 3. Auto Track Sync
        if self.auto_sync_active and not (self.dome_sync_worker and self.dome_sync_worker.isRunning()):
            # Only sync if telescope is tracking
            if self.motion_state.tracking_active:
                with self.motion_state._lock:
                    position_valid = getattr(self.motion_state, "telescope_position_valid", True)
                    position_error = getattr(self.motion_state, "telescope_position_error", "")
                    current_az = self.motion_state.dome_az_deg
                    ha_deg = self.motion_state.sim_ha_deg
                    dec_deg = self.motion_state.sim_dec_deg

                if not position_valid:
                    logger.warning(f"Auto Track Sync skipped: {position_error}")
                    return
                if not math.isfinite(dec_deg) or not -90.0 <= dec_deg <= 90.0:
                    logger.warning(f"Auto Track Sync skipped: invalid DEC {dec_deg:.6f}°")
                    return
                
                # Calculate target AZ using same logic as DomeSyncWorker
                lst_hours = self.astro.get_current_lst_hours_cached()
                ha_hours = ha_deg / 15.0
                ra_hours = (lst_hours - ha_hours) % 24.0
                astro_params = self.astro.calculate_parameters(ra_hours, dec_deg)
                
                target_az = corrected_dome_azimuth(
                    astro_params.get("az_deg", 0.0),
                    astro_params.get("alt_deg", 0.0),
                    ha_deg,
                    self.astro.location.lat.deg,
                )
                
                delta = target_az - current_az
                if delta < -180: delta += 360
                elif delta > 180: delta -= 360
                
                tolerance = float(os.environ.get("DOME_SYNC_TOLERANCE_DEG", "5.0"))
                if abs(delta) > tolerance:
                    logger.info(f"Auto Track Sync triggered: error {abs(delta):.1f}° > tolerance {tolerance:.1f}°")
                    self._handle_dome_sync_request()

    def _update_display_fast(self):
        """10Hz display update for coordinates (No expensive Astropy transforms here)."""
        lst_hours = self.astro.get_current_lst_hours_cached()
        sim_ha_hours = self.motion_state.sim_ha_deg / 15.0

        current_ra_hours = (lst_hours - sim_ha_hours) % 24.0
        current_dec_deg = self.motion_state.sim_dec_deg

        # Store for sync handler (works in both REAL and SIM modes)
        self._last_ra_hours = current_ra_hours
        self._last_dec_deg = current_dec_deg

        # Format strings (Cheap)
        ra_hms = LegacyDecoder.decimal_hours_to_hms(current_ra_hours)
        hra_hms = LegacyDecoder.decimal_hours_to_hms(sim_ha_hours if sim_ha_hours >= 0 else sim_ha_hours + 24)
        dec_dms = LegacyDecoder.decimal_deg_to_dms(current_dec_deg)

        # Update text displays
        self.lcd_ra.setText(ra_hms)
        self.lcd_hra.setText(hra_hms)
        
        dec_parts = dec_dms.split(':')
        if len(dec_parts) == 3:
            self.lcd_dec_deg.setText(dec_parts[0])
            self.lcd_dec_min.setText(dec_parts[1])
            self.lcd_dec_sec.setText(dec_parts[2])

        self.lbl_raw_ra.setText(f"SIM HA: {self.motion_state.sim_ha_deg:.4f}°")
        self.lbl_raw_dec.setText(f"SIM DEC: {current_dec_deg:.4f}°")

    def _update_astro_slow(self):
        """1Hz astrometry update (Expensive SkyCoord transforms)."""
        lst_hours = self.astro.get_current_lst_hours_cached()
        sim_ha_hours = self.motion_state.sim_ha_deg / 15.0
        current_ra_hours = (lst_hours - sim_ha_hours) % 24.0
        current_dec_deg = self.motion_state.sim_dec_deg

        # Compute expensive astro params (Alt/Az/JD)
        astro_data = self.astro.calculate_parameters(current_ra_hours, current_dec_deg)

        # Update UI
        self.lcd_az.setText(f"{astro_data.get('az_deg', 0.0):.1f}°")
        self.lcd_alt.setText(f"{astro_data.get('alt_deg', 0.0):.1f}°")
        self._update_airmass_display(astro_data)
        
        lst_hms = LegacyDecoder.decimal_hours_to_hms(lst_hours)
        self.lbl_lst.setText(lst_hms)
        self.lbl_jd.setText(f"{astro_data.get('jd', 0.0):.5f}")

    def _update_airmass_display(self, astro_data):
        if not hasattr(self, "lbl_airmass"):
            return

        if not astro_data:
            self.lbl_airmass.setText("--")
            return

        try:
            airmass = float(astro_data.get("airmass"))
        except (TypeError, ValueError):
            self.lbl_airmass.setText("--")
            return

        if math.isfinite(airmass):
            self.lbl_airmass.setText(f"{airmass:.2f}")
        else:
            self.lbl_airmass.setText("--")

    def _enforce_altitude_motion_limit(self):
        """Block any active mount motion that would cross the altitude floor."""
        guard = self.altitude_guard

        with self.motion_state._lock:
            position_valid = getattr(self.motion_state, "telescope_position_valid", True)
            position_error = getattr(self.motion_state, "telescope_position_error", "")
            ha_deg = self.motion_state.sim_ha_deg
            dec_deg = self.motion_state.sim_dec_deg
            tracking_active = self.motion_state.tracking_active

            ra_source = None
            ra_speed = None
            ra_dir = 0
            ra_label = ""
            if self.motion_state.ra_direction != "NONE":
                ra_source = "manual"
                ra_speed = self.motion_state.ra_speed
                ra_dir = -1 if self.motion_state.ra_direction == "EAST" else 1
                ra_label = f"RA {self.motion_state.ra_direction}"
            elif self.motion_state.slew_ra_speed:
                ra_source = "slew"
                ra_speed = self.motion_state.slew_ra_speed
                ra_dir = self.motion_state.slew_ra_dir
                ra_label = "slew RA"

            dec_source = None
            dec_speed = None
            dec_dir = 0
            dec_label = ""
            if self.motion_state.dec_direction != "NONE":
                dec_source = "manual"
                dec_speed = self.motion_state.dec_speed
                dec_dir = 1 if self.motion_state.dec_direction == "NORTH" else -1
                dec_label = f"DEC {self.motion_state.dec_direction}"
            elif self.motion_state.slew_dec_speed:
                dec_source = "slew"
                dec_speed = self.motion_state.slew_dec_speed
                dec_dir = self.motion_state.slew_dec_dir
                dec_label = "slew DEC"

        if self.motion_state.mode == "REAL" and not position_valid:
            if tracking_active:
                self.motion_state.deactivate_tracking()
            if ra_source == "manual":
                self.motion_state.set_ra_direction("NONE")
            elif ra_source == "slew":
                self.slew_engine.abort()
            if dec_source == "manual":
                self.motion_state.set_dec_direction("NONE")
            elif dec_source == "slew":
                self.slew_engine.abort()

            message = position_error or "Invalid telescope telemetry; motion blocked."
            self.motion_state.set_safety_limit(True, message)
            self._emit_altitude_safety_alert(message)
            return

        blocked = []
        abort_slew = False
        tracking_blocked = False
        ra_blocked = False
        dec_blocked = False
        tracking_ha_rate = 0.0
        ra_ha_rate = 0.0
        dec_rate = 0.0

        def check_motion(label, ha_rate=0.0, dec_rate=0.0):
            blocked_motion, current_alt, projected_alt = guard.motion_would_cross_floor(
                ha_deg,
                dec_deg,
                ha_rate_deg_sec=ha_rate,
                dec_rate_deg_sec=dec_rate,
            )
            if blocked_motion:
                blocked.append(
                    f"{label} ({current_alt:.1f}° -> {projected_alt:.1f}°; limit {guard.min_altitude_deg:.1f}°)"
                )
            return blocked_motion

        if tracking_active:
            tracking_ha_rate = guard.ha_rate_for_ra_motion("TRACK", 1)
            if check_motion("tracking", ha_rate=tracking_ha_rate):
                tracking_blocked = True
                self.motion_state.deactivate_tracking()

        if ra_source:
            ra_ha_rate = guard.ha_rate_for_ra_motion(ra_speed, ra_dir)
            if check_motion(ra_label, ha_rate=ra_ha_rate):
                ra_blocked = True
                if ra_source == "manual":
                    self.motion_state.set_ra_direction("NONE")
                else:
                    abort_slew = True

        if dec_source:
            dec_rate = guard.dec_rate_for_dec_motion(dec_speed, dec_dir)
            if check_motion(dec_label, dec_rate=dec_rate):
                dec_blocked = True
                if dec_source == "manual":
                    self.motion_state.set_dec_direction("NONE")
                else:
                    abort_slew = True

        active_components = [
            tracking_active and not tracking_blocked,
            bool(ra_source) and not ra_blocked,
            bool(dec_source) and not dec_blocked,
        ]
        if sum(1 for active in active_components if active) > 1:
            combined_blocked, current_alt, projected_alt = guard.motion_would_cross_floor(
                ha_deg,
                dec_deg,
                ha_rate_deg_sec=(tracking_ha_rate if tracking_active and not tracking_blocked else 0.0)
                + (ra_ha_rate if ra_source and not ra_blocked else 0.0),
                dec_rate_deg_sec=dec_rate if dec_source and not dec_blocked else 0.0,
            )
            if combined_blocked:
                blocked.append(
                    f"combined motion ({current_alt:.1f}° -> {projected_alt:.1f}°; "
                    f"limit {guard.min_altitude_deg:.1f}°)"
                )
                if tracking_active and not tracking_blocked:
                    self.motion_state.deactivate_tracking()
                if ra_source and not ra_blocked:
                    if ra_source == "manual":
                        self.motion_state.set_ra_direction("NONE")
                    else:
                        abort_slew = True
                if dec_source and not dec_blocked:
                    if dec_source == "manual":
                        self.motion_state.set_dec_direction("NONE")
                    else:
                        abort_slew = True

        if abort_slew:
            self.slew_engine.abort()

        if blocked:
            message = "Altitude safety blocked " + "; ".join(blocked)
            self.motion_state.set_safety_limit(True, message)
            self._emit_altitude_safety_alert(message)
            return

        try:
            current_alt = guard.altitude_for_mount_position(ha_deg, dec_deg)
            if math.isfinite(current_alt) and current_alt < guard.min_altitude_deg:
                message = (
                    f"Altitude {current_alt:.1f}° is below {guard.min_altitude_deg:.1f}°; "
                    "only recovery motion is allowed."
                )
                self.motion_state.set_safety_limit(True, message)
                return
        except Exception:
            pass

        self.motion_state.set_safety_limit(False)

    def _emit_altitude_safety_alert(self, message):
        now = time.monotonic()
        if (
            message == self._last_altitude_alert_message
            and (now - self._last_altitude_alert_at) < 2.0
        ):
            return

        self._last_altitude_alert_message = message
        self._last_altitude_alert_at = now
        QApplication.beep()
        logger.warning(f"SAFETY: {message}")
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(f"SAFETY: {message}", 5000)
        
    def _update_motor_status(self):
        """Update motor status label from current MotionState."""
        s = self.motion_state
        ra_txt = "OFF"
        if s.ra_direction != "NONE":
            ra_txt = f"{s.ra_speed} ({s.ra_direction})"
        elif s.slew_ra_speed:
            dir_str = "WEST" if s.slew_ra_dir > 0 else "EAST"
            ra_txt = f"AUTO {s.slew_ra_speed} ({dir_str})"

        dec_txt = "OFF"
        if s.dec_direction != "NONE":
            dec_txt = f"{s.dec_speed} ({s.dec_direction})"
        elif s.slew_dec_speed:
            dir_str = "NORTH" if s.slew_dec_dir > 0 else "SOUTH"
            dec_txt = f"AUTO {s.slew_dec_speed} ({dir_str})"

        trk = "ON" if s.tracking_active else "OFF"
        dome = s.dome_state

        self.lbl_motor_status.setText(
            f"RA: {ra_txt} | DEC: {dec_txt} | TRK: {trk} | DOME: {dome}"
        )

    # ═══════════════════════════════════════════════════════════
    # COOLDOWN
    # ═══════════════════════════════════════════════════════════
    def _start_cooldown(self):
        self.motion_state.cooldown_active = True
        self.cooldown_ticks = 6
        self.motion_panel.btn_slew.setEnabled(False)
        self.cooldown_timer.start(1000)
        self.status_bar.showMessage("MOTOR COOLDOWN: 6s")

    def _cooldown_tick(self):
        self.cooldown_ticks -= 1
        if self.cooldown_ticks <= 0:
            self.cooldown_timer.stop()
            self.motion_state.cooldown_active = False
            self.motion_panel.btn_slew.setEnabled(True)
            self.status_bar.showMessage("System Ready. Cooldown complete.")
        else:
            self.status_bar.showMessage(f"MOTOR COOLDOWN: {self.cooldown_ticks}s")

    # ═══════════════════════════════════════════════════════════
    # ACTION HANDLERS
    # ═══════════════════════════════════════════════════════════
    def _handle_manual_dome_move(self, direction):
        """Abort any active sync before manual move, then execute."""
        if self.auto_sync_active:
            self.btn_auto_track_sync.setChecked(False)  # Disables auto_sync_active via signal
            
        if self.dome_sync_worker and self.dome_sync_worker.isRunning():
            self.dome_sync_worker.abort()
            
        if direction == "CW":
            self.motion_state.set_dome_cw()
        elif direction == "CCW":
            self.motion_state.set_dome_ccw()
        elif direction == "OFF":
            self.motion_state.set_dome_off()

    def _toggle_auto_track_sync(self, checked):
        self.auto_sync_active = checked
        if checked:
            self.status_bar.showMessage("Auto Track Sync ENABLED.")
        else:
            self.status_bar.showMessage("Auto Track Sync DISABLED.")
            
    def _handle_dome_sync_request(self):
        """Start Dome Synchronization in a background thread."""
        if self.dome_sync_worker and self.dome_sync_worker.isRunning():
            self.status_bar.showMessage("Dome Sync already running.")
            return
            
        self.dome_sync_worker = DomeSyncWorker(self.motion_state, self.astro)
        self.dome_sync_worker.sync_finished.connect(self._on_dome_sync_finished)
        self.dome_sync_worker.start()
        self.status_bar.showMessage("Dome Sync Started...")
        
    @pyqtSlot(str)
    def _on_dome_sync_finished(self, msg):
        self.status_bar.showMessage(msg)
        
    def _handle_slew_request(self, ra_str, dec_str):
        """Handle GOTO TARGET button press."""
        try:
            ra_deg = self._parse_coordinate(ra_str, is_ra=True)
            dec_deg = self._parse_coordinate(dec_str)

            if ra_deg is None or dec_deg is None:
                QMessageBox.warning(self, "Input Error", "Invalid coordinate format.")
                return

            success, msg = self.slew_engine.start_slew(ra_deg, dec_deg)
            if success:
                self.status_bar.showMessage(msg)
            else:
                QApplication.beep()
                QMessageBox.critical(self, "Safety Interlock", msg)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def _handle_stop_request(self):
        """Handle EMERGENCY STOP button."""
        if self.auto_sync_active:
            self.btn_auto_track_sync.setChecked(False)
            
        if self.dome_sync_worker and self.dome_sync_worker.isRunning():
            self.dome_sync_worker.abort()
            
        was_active = (
            self.motion_state.is_slewing or
            self.motion_state.ra_direction != "NONE" or
            self.motion_state.dec_direction != "NONE"
        )

        self.slew_engine.abort()
        self.motion_state.emergency_stop()

        if was_active:
            self.motion_state.request_cooldown = True

        self.status_bar.showMessage("🛑 EMERGENCY STOP — All motion cleared.")

    def _handle_park_request(self):
        """
        Park the telescope at its physical mechanical home position.

        Physical park targets (no offsets applied):
          - HRA  = 00:00:00 (Meridian)
          - DEC  = User's calibrated home position (dec_home_deg from state.json),
                   fallback +29:21:00 (29.35°)
          - Dome = 0° (North)

        No offset compensation is performed. The telescope moves to the
        raw home position as defined by dec_home_deg, HRA=0, Dome=0.
        """
        # ── Safety: Reject if already slewing or in cooldown ──
        if self.motion_state.is_slewing:
            QMessageBox.warning(
                self, "Park Blocked",
                "A slew is already in progress. Stop it before parking."
            )
            return
        if self.motion_state.cooldown_active:
            QMessageBox.warning(
                self, "Park Blocked",
                "Motors are in cooldown. Wait for cooldown to finish."
            )
            return

        self.handle_log("INFO", "PARK Request initiated. Moving to physical home position...")

        # ── 0. Turn off tracking before parking ──
        # Tracking adds sidereal rate to HA continuously, which fights the
        # slew engine's attempt to pin HA=0. This causes endless Fine 2
        # oscillation on RA and prevents the slew from completing.
        if self.motion_state.tracking_active:
            self.motion_state.deactivate_tracking()
            self.handle_log("INFO", "Tracking disabled for park operation.")
            logger.info("PARK: Tracking deactivated to prevent RA oscillation.")

        # Disable auto track sync during parking
        if self.auto_sync_active:
            self.btn_auto_track_sync.setChecked(False)

        # ── 1. Determine physical park DEC ──
        # Use the user-calibrated home position; fallback to +29:21:00
        FALLBACK_DEC_DEG = 29.633305555555556  # +29:37:59.9
        park_dec_home = self.telemetry_worker.coordinator.dec_home_deg
        if park_dec_home is None:
            park_dec_deg = FALLBACK_DEC_DEG
            logger.warning(
                f"DEC Home not set. Using fallback park DEC = {FALLBACK_DEC_DEG}°"
            )
            self.handle_log(
                "WARNING",
                f"DEC Home not calibrated! Parking to default {FALLBACK_DEC_DEG}°. "
                "Set DEC Home for accurate parking."
            )
        else:
            park_dec_deg = park_dec_home
            logger.info(f"Park DEC from calibrated home: {park_dec_deg:.4f}°")

        # ── 2. Physical park HRA = 0 hours → RA = LST ──
        park_ha_deg = 0.0  # Meridian
        current_lst = self.astro.get_current_lst_hours()
        park_ra_deg = (current_lst * 15.0) % 360.0  # RA = LST when HRA = 0

        logger.info(
            f"PARK targets → HRA=0.0h, DEC={park_dec_deg:.4f}°, DOME=0.0° | "
            f"RA(from LST)={park_ra_deg:.4f}° (No offsets applied)"
        )

        # ── 3. Execute Slew (bypass zenith limit — park is a controlled maneuver) ──
        # fixed_ha_deg=0 pins the HA target so it doesn't drift as LST advances.
        success, msg = self.slew_engine.start_slew(
            park_ra_deg, park_dec_deg,
            skip_max_alt=True,
            fixed_ha_deg=park_ha_deg
        )
        if success:
            self.status_bar.showMessage(f"Parking telescope... {msg}")
        else:
            QMessageBox.critical(self, "Parking Interlock", f"Cannot Park: {msg}")
            return

        # ── 4. Dome parking ──
        # Dome movement to 0° (North) is handled by dome sync.
        if self.dome_sync_worker and self.dome_sync_worker.isRunning():
            self.dome_sync_worker.abort()
            
        self.dome_sync_worker = DomeSyncWorker(self.motion_state, self.astro, park_mode=True)
        self.dome_sync_worker.sync_finished.connect(self._on_dome_sync_finished)
        self.dome_sync_worker.start()
        self.status_bar.showMessage(f"Parking telescope and dome... {msg}")
        self.handle_log("INFO", "Park initiated. Move dome to 0° (North) manually if needed.")

    def _handle_set_ra_offset(self, ra_str):
        """SET RA: User enters the ACTUAL RA of the centered star."""
        try:
            actual_ra_hours = self._parse_hms_to_hours(ra_str)
            if actual_ra_hours is None:
                QMessageBox.warning(self, "Input Error", "Invalid RA format. Use HH:MM:SS")
                return

            current_ra_hours = getattr(self, '_last_ra_hours', None)
            if current_ra_hours is None:
                QMessageBox.warning(self, "Offset Error", "No RA telemetry yet. Wait for encoder data.")
                return

            # Apply correction: minor_hra_adj += shortest(current - actual) * 3600
            # Multiplier is 3600 because the HRA pipeline uses time-arcseconds
            # (3600 time-arcsec = 1 hour), NOT angular arcseconds (54000"/hour).
            ra_error_hours = (current_ra_hours - actual_ra_hours + 12.0) % 24.0 - 12.0
            hra_correction = int(round(ra_error_hours * 3600.0))
            LegacyDecoder.minor_hra_adj += hra_correction

            # Clamp — wider limit for manual calibration (±10°)
            MAX_BIAS = 36000
            LegacyDecoder.minor_hra_adj = max(-MAX_BIAS, min(MAX_BIAS, LegacyDecoder.minor_hra_adj))

            # Persist to disk
            self._save_offsets_to_disk()
            self._update_offset_status_label()

            msg = f"RA offset set: {hra_correction:+d}\" (total: {LegacyDecoder.minor_hra_adj:.0f}\")"
            logger.info(msg)
            self.status_bar.showMessage(f"✓ {msg}")

        except Exception as e:
            QMessageBox.warning(self, "Offset Error", f"RA offset failed: {e}")

    def _handle_set_dec_offset(self, dec_str):
        """SET DEC: User enters the ACTUAL DEC of the centered star."""
        try:
            actual_dec_deg = self._parse_coordinate(dec_str)
            if actual_dec_deg is None:
                QMessageBox.warning(self, "Input Error", "Invalid DEC format. Use ±DD:MM:SS")
                return

            current_dec_deg = getattr(self, '_last_dec_deg', None)
            if current_dec_deg is None:
                QMessageBox.warning(self, "Offset Error", "No DEC telemetry yet. Wait for encoder data.")
                return

            # Apply correction: minor_dec_adj += (actual - current) * 3600
            dec_correction = int((actual_dec_deg - current_dec_deg) * 3600.0)
            LegacyDecoder.minor_dec_adj += dec_correction

            # Clamp — wider limit for manual calibration (±10°)
            MAX_BIAS = 36000
            LegacyDecoder.minor_dec_adj = max(-MAX_BIAS, min(MAX_BIAS, LegacyDecoder.minor_dec_adj))

            # Persist to disk
            self._save_offsets_to_disk()
            self._update_offset_status_label()

            msg = f"DEC offset set: {dec_correction:+d}\" (total: {LegacyDecoder.minor_dec_adj:.0f}\")"
            logger.info(msg)
            self.status_bar.showMessage(f"✓ {msg}")

        except Exception as e:
            QMessageBox.warning(self, "Offset Error", f"DEC offset failed: {e}")

    def _handle_set_dome_offset(self, dome_str):
        """SET DOME: User enters the ACTUAL dome azimuth in degrees."""
        try:
            actual_dome_az = float(dome_str)

            # Sync Dome via telemetry worker (sets dome_offset_counts in MountCoordinator)
            if self.telemetry_worker:
                # We need the current DEC too for the existing sync API
                current_dec = getattr(self, '_last_dec_deg', 32.167)
                self.telemetry_worker.request_sync(current_dec, actual_dome_az)

                self._update_offset_status_label()
                msg = f"Dome offset synced to {actual_dome_az:.1f}°"
                logger.info(msg)
                self.status_bar.showMessage(f"✓ {msg}")
            else:
                QMessageBox.warning(self, "Offset Error", "Not connected. Cannot set dome offset.")

        except ValueError:
            QMessageBox.warning(self, "Input Error", "Invalid dome azimuth. Enter degrees (e.g., 180.5)")
        except Exception as e:
            QMessageBox.warning(self, "Offset Error", f"Dome offset failed: {e}")

    def _handle_clear_offsets(self):
        """Clear all stored offset corrections."""
        LegacyDecoder.minor_hra_adj = 0.0
        LegacyDecoder.minor_dec_adj = 0.0

        # Persist cleared offsets to disk
        self._save_offsets_to_disk()
        self._update_offset_status_label()

        logger.info("All offsets cleared (RA, DEC, Dome)")
        self.status_bar.showMessage("✓ All offsets cleared.")

    def _save_offsets_to_disk(self):
        """Persist current minor_hra_adj and minor_dec_adj to state.json."""
        if self.telemetry_worker and hasattr(self.telemetry_worker, 'coordinator'):
            self.telemetry_worker.coordinator._save_state()

    def _update_offset_status_label(self):
        """Update the offset status label in the motion panel."""
        hra = LegacyDecoder.minor_hra_adj
        dec = LegacyDecoder.minor_dec_adj
        self.motion_panel.lbl_offset_status.setText(
            f"Offsets: RA {hra:+.0f}\" | DEC {dec:+.0f}\""
        )
        # Color: green if offsets are active, gray if zero
        if hra != 0 or dec != 0:
            self.motion_panel.lbl_offset_status.setStyleSheet(
                "color: #66bb6a; font-size: 11px; font-weight: bold; padding: 2px 4px;"
            )
        else:
            self.motion_panel.lbl_offset_status.setStyleSheet(
                "color: #78909c; font-size: 11px; padding: 2px 4px;"
            )

    def _init_dec_home_status(self):
        """Restore DEC home status indicator from persisted coordinator state on startup."""
        home_deg = self.telemetry_worker.coordinator.dec_home_deg
        self.motion_panel.update_home_status(home_deg)

    def _handle_set_dec_home(self, dec_str):
        """Handle SET HOME button: Observer enters DEC dial reading to calibrate encoder."""
        try:
            if not dec_str or not dec_str.strip():
                QMessageBox.warning(self, "Input Error", "Enter the DEC value from the mechanical dials.")
                return

            # Parse DMS to decimal degrees (reuse existing helper)
            home_dec_deg = self._parse_coordinate(dec_str)
            if home_dec_deg is None:
                QMessageBox.warning(self, "Input Error", "Invalid DEC format. Use \u00b1DD:MM:SS")
                return

            # Validate range
            if abs(home_dec_deg) > 90.0:
                QMessageBox.warning(self, "Range Error", "DEC must be between -90\u00b0 and +90\u00b0")
                return

            # Call the thread-safe telemetry worker method
            self.telemetry_worker.request_set_dec_home(home_dec_deg)

            # Update UI indicators
            self.motion_panel.update_home_status(home_dec_deg)
            self._update_offset_status_label()

            msg = f"DEC Home set to {dec_str.strip()} ({home_dec_deg:.4f}\u00b0)"
            logger.info(msg)
            self.status_bar.showMessage(f"\u2713 {msg}")

        except RuntimeError as e:
            QMessageBox.critical(self, "Homing Error", str(e))
        except Exception as e:
            QMessageBox.warning(self, "Homing Error", f"DEC Home failed: {e}")

    def _parse_hms_to_hours(self, hms_str):
        """Parse 'HH:MM:SS' or 'HH:MM:SS.s' to decimal hours."""
        try:
            parts = hms_str.strip().split(':')
            h = float(parts[0])
            m = float(parts[1]) if len(parts) > 1 else 0
            s = float(parts[2]) if len(parts) > 2 else 0
            return (h + m / 60.0 + s / 3600.0) % 24.0
        except Exception:
            return None

    def _parse_coordinate(self, text, is_ra=False):
        try:
            if ':' in text:
                parts = list(map(float, text.split(':')))
                sign = -1 if str(text).strip().startswith('-') else 1
                deg = abs(parts[0]) + abs(parts[1]) / 60.0
                if len(parts) > 2:
                    deg += abs(parts[2]) / 3600.0
                if is_ra and " " not in text:
                    return (deg * 15.0) % 360.0
                return sign * deg
            return float(text)
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════
    # CONNECTION
    # ═══════════════════════════════════════════════════════════
    def toggle_connection(self):
        if self.btn_connect.isChecked():
            self.btn_connect.setText("CONNECTING...")

            # Connect Encoder Arduinos (if REAL mode)
            if self.motion_state.mode == "REAL":
                self.telemetry_worker.start()

            # Connect DUO Control Arduino
            try:
                import json
                external_root = os.environ.get('STCS_EXTERNAL_ROOT', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                config_path = os.path.join(external_root, 'config', 'settings.json')
                with open(config_path, 'r') as f:
                    config = json.load(f)

                ctrl_cfg = config.get('connections', {}).get('control_arduino', {})
                ctrl_sn = ctrl_cfg.get('serial_number', '')

                if ctrl_sn and ctrl_sn != "PLACEHOLDER_DUO_SERIAL_NUMBER":
                    self.control_serial = ControlSerial(
                        serial_number=ctrl_sn,
                        baud_rate=ctrl_cfg.get('baud_rate', 115200),
                        timeout=ctrl_cfg.get('timeout', 1)
                    )
                    self.control_serial.connect()
                    self._set_indicator("CTRL", True)
                else:
                    logger.warning("DUO serial number is placeholder. Control Arduino not connected.")
                    self._set_indicator("CTRL", False)

            except Exception as e:
                logger.error(f"Control Arduino connection failed: {e}")
                self._set_indicator("CTRL", False)

            # Update indicators for simulation mode
            if self.motion_state.mode == "SIMULATION":
                self._set_indicator("RA", True)
                self._set_indicator("DEC", True)
                self._set_indicator("DOME", True)

            self.btn_connect.setText("DISCONNECT SYSTEM")
            self.btn_connect.setStyleSheet(
                "background-color: #d32f2f; color: white; font-weight: bold; padding: 8px;"
            )
        else:
            self.btn_connect.setText("CONNECT TELESCOPE")
            self.btn_connect.setStyleSheet("font-weight: bold; padding: 8px;")

            if self.motion_state.mode == "REAL":
                self.telemetry_worker.stop()

            if self.control_serial:
                self.control_serial.close()
                self.control_serial = None

            self.reset_ui_status()

    def _set_indicator(self, name, online):
        lbl = self.status_indicators.get(name)
        if not lbl:
            return
        if online:
            lbl.setText(f"{name}: ONLINE")
            lbl.setStyleSheet(
                "color: #00cc00; font-weight: bold; border: 1px solid #333; "
                "padding: 5px; background-color: #111; border-radius: 4px;"
            )
        else:
            lbl.setText(f"{name}: OFFLINE")
            lbl.setStyleSheet(
                "color: #ff4444; font-weight: bold; border: 1px solid #333; "
                "padding: 5px; background-color: #111; border-radius: 4px;"
            )

    # ═══════════════════════════════════════════════════════════
    # TELEMETRY HANDLERS
    # ═══════════════════════════════════════════════════════════
    @pyqtSlot(dict)
    def feed_gps_to_astrometry(self, gps_data):
        self.telemetry_worker.coordinator.astro.update_from_gps(gps_data)
        self.astro.update_from_gps(gps_data)
        self._accept_gps_time(gps_data)
        self._accept_gps_position(gps_data)
        self._update_gps_position_display()

    @pyqtSlot(bool, str)
    def handle_gps_status(self, success, message):
        """Track GPS hardware status for the main header indicator."""
        self._gps_status_message = message
        self._gps_connected = bool(success and message.startswith("Connected"))
        if not self._gps_connected and not success:
            self._gps_time_utc = None
            self._gps_time_monotonic = None
            self._last_gps_utc_dt = None
            self._last_gps_position = None
        self._update_gps_status_label()
        self._update_ist_display()
        self._update_gps_position_display()

    def _accept_gps_time(self, gps_data):
        """Accept strictly newer GPS UTC samples and use monotonic time between them."""
        if not gps_data:
            return

        dt = gps_data.get("utc_time")
        if dt is None:
            return

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        if self._last_gps_utc_dt is not None and dt <= self._last_gps_utc_dt:
            return

        self._last_gps_utc_dt = dt
        self._gps_time_utc = dt
        self._gps_time_monotonic = time.monotonic()

    def _accept_gps_position(self, gps_data):
        """Store the latest valid GPS fix position for the environment panel."""
        if not gps_data:
            return

        if gps_data.get("fix_quality", 0) == 0:
            self._last_gps_position = None
            return

        try:
            lat = float(gps_data.get("latitude"))
            lon = float(gps_data.get("longitude"))
            alt = float(gps_data.get("altitude"))
        except (TypeError, ValueError):
            return

        if not (
            math.isfinite(lat)
            and math.isfinite(lon)
            and math.isfinite(alt)
            and -90.0 <= lat <= 90.0
            and -180.0 <= lon <= 180.0
        ):
            return

        self._last_gps_position = {
            "latitude": lat,
            "longitude": lon,
            "altitude": alt,
        }

    def _update_gps_position_display(self):
        if not all(
            hasattr(self, name)
            for name in ("val_gps_lat", "val_gps_lon", "val_gps_alt")
        ):
            return

        if not self._gps_connected or not self._last_gps_position:
            self.val_gps_lat.setText("Latitude: --")
            self.val_gps_lon.setText("Longitude: --")
            self.val_gps_alt.setText("Altitude: --")
            return

        pos = self._last_gps_position
        self.val_gps_lat.setText(f"Latitude: {pos['latitude']:.6f}°")
        self.val_gps_lon.setText(f"Longitude: {pos['longitude']:.6f}°")
        self.val_gps_alt.setText(f"Altitude: {pos['altitude']:.1f} m")

    def _get_ist_time_and_source(self):
        if self._gps_connected and self._gps_time_utc and self._gps_time_monotonic:
            elapsed = time.monotonic() - self._gps_time_monotonic
            utc_now = self._gps_time_utc + timedelta(seconds=elapsed)
            return utc_now.astimezone(IST_TIMEZONE), "GPS"
        return datetime.now(IST_TIMEZONE), "SYSTEM"

    def _update_ist_display(self):
        if not hasattr(self, "lbl_ist_time"):
            return

        ist_now, source = self._get_ist_time_and_source()
        ist_text = ist_now.strftime("%H:%M:%S") + f".{ist_now.microsecond // 100000}"
        self.lbl_ist_time.setText(f"IST: {ist_text} ({source})")
        color = "#00ffcc" if source == "GPS" else "#ffcc66"
        self.lbl_ist_time.setStyleSheet(
            f"color: {color}; font-weight: bold; border: 1px solid #333; "
            "padding: 5px; background-color: #111; border-radius: 4px;"
        )

    def _update_gps_status_label(self):
        if not hasattr(self, "lbl_gps_status"):
            return

        if self._gps_connected:
            text = "GPS: CONNECTED"
            color = "#00cc00"
        elif "Scanning" in self._gps_status_message or "Auto" in self._gps_status_message:
            text = "GPS: SEARCHING"
            color = "#ffcc66"
        else:
            text = "GPS: DISCONNECTED"
            color = "#ff4444"

        self.lbl_gps_status.setText(text)
        self.lbl_gps_status.setToolTip(self._gps_status_message)
        self.lbl_gps_status.setStyleSheet(
            f"color: {color}; font-weight: bold; border: 1px solid #333; "
            "padding: 5px; background-color: #111; border-radius: 4px;"
        )

    @pyqtSlot(bool, str)
    def handle_connection_status(self, success, message):
        if success:
            for name in ["RA", "DEC", "DOME"]:
                self._set_indicator(name, True)
        else:
            self.btn_connect.setChecked(False)
            self.btn_connect.setText("CONNECT TELESCOPE")
            self.btn_connect.setStyleSheet("font-weight: bold; padding: 8px;")
            self.reset_ui_status()

    @pyqtSlot(dict)
    def update_telemetry(self, data):
        """Handle telemetry from real encoder hardware."""
        if self.motion_state.mode != "REAL":
            return  # In simulation mode, we use _update_sim_telemetry instead

        self.lcd_ra.setText(data.get("ra_hms", "00:00:00"))
        self.lcd_hra.setText(data.get("hra_hms", "00:00:00"))
        self.lcd_dome.setText(f"{data.get('dome_az', 0.0):.1f}°")
        
        # Calculate AZ and ALT dynamically from RA/DEC if possible
        ra_decimal = data.get('ra_decimal', 0.0)
        dec_decimal = data.get('dec_decimal', 0.0)
        clamped_dec = max(-90.0, min(90.0, dec_decimal))
        try:
            astro_data = self.astro.calculate_parameters(ra_decimal, clamped_dec)
            self.lcd_az.setText(f"{astro_data.get('az_deg', 0.0):.1f}°")
            self.lcd_alt.setText(f"{astro_data.get('alt_deg', 0.0):.1f}°")
            self._update_airmass_display(astro_data)
        except Exception as e:
            logger.error(f"Astrometry error UI: {e}")
            self.lcd_az.setText("0.0°")
            self.lcd_alt.setText("0.0°")
            self._update_airmass_display(None)

        dec_str = data.get("dec_dms", "+00:00:00")
        parts = dec_str.split(':')
        if len(parts) == 3:
            self.lcd_dec_deg.setText(parts[0])
            self.lcd_dec_min.setText(parts[1])
            self.lcd_dec_sec.setText(parts[2])
        self.lbl_lst.setText(data.get('lst_hms', '00:00:00'))
        self.lbl_jd.setText(f"{data.get('jd', 0.0):.5f}")
        self.lbl_raw_ra.setText(f"HRA: {data.get('raw_hra', 0)}")
        raw_dec_encoder = data.get('raw_dec_encoder', data.get('raw_dec', 0))
        corrected_dec = data.get('raw_dec', raw_dec_encoder)
        if data.get('dec_index_home_active', False):
            self.lbl_raw_dec.setText(f"DEC RAW: {raw_dec_encoder} (INDEX HOME)")
        else:
            self.lbl_raw_dec.setText(f"DEC RAW: {raw_dec_encoder} | CORR: {corrected_dec}")
        self.lbl_raw_dome.setText(f"DOME: {data.get('raw_dome', 0)}")

        # Feed real positions into motion state for INDI driver
        ra_hours = data.get('ra_decimal', 0.0)
        dec_deg = data.get('dec_decimal', 0.0)
        hra_hours = data.get('hra_decimal', 0.0)
        try:
            dec_deg = float(dec_deg)
        except (TypeError, ValueError):
            dec_deg = float("nan")
        try:
            hra_hours = float(hra_hours)
        except (TypeError, ValueError):
            hra_hours = float("nan")

        dec_valid = math.isfinite(dec_deg) and -90.0 <= dec_deg <= 90.0
        hra_valid = math.isfinite(hra_hours)
        position_valid = dec_valid and hra_valid

        # Store for sync handler
        self._last_ra_hours = ra_hours
        self._last_dec_deg = dec_deg

        with self.motion_state._lock:
            if position_valid:
                self._invalid_telemetry_count = 0
                self.motion_state.sim_ha_deg = hra_hours * 15.0
                self.motion_state.sim_dec_deg = dec_deg
                self.motion_state.telescope_position_valid = True
                self.motion_state.telescope_position_error = ""
            else:
                self._invalid_telemetry_count += 1
                if self._invalid_telemetry_count >= 3:
                    self.motion_state.telescope_position_valid = False
                    if not hra_valid:
                        self.motion_state.telescope_position_error = (
                            f"Invalid HRA telemetry: {hra_hours}"
                        )
                    else:
                        self.motion_state.telescope_position_error = (
                            f"Invalid DEC telemetry: {dec_deg:.6f} deg outside -90..+90"
                        )
            self.motion_state.dome_az_deg = data.get('dome_az', 0.0)

    @pyqtSlot(dict)
    def update_weather(self, data):
        self.val_temp.setText(f"{data['temp_c']:.1f} C")
        self.val_humidity.setText(f"{data['humidity_percent']:.1f} %")
        with self.motion_state._lock:
            self.motion_state.weather_data = data

    @pyqtSlot(str)
    def handle_safety_alert(self, msg):
        QApplication.beep()
        self.status_bar.showMessage(f"SAFETY: {msg}")

    @pyqtSlot(str, str)
    def handle_log(self, level, msg):
        self.status_bar.showMessage(msg)

    # ═══════════════════════════════════════════════════════════
    # WINDOW OPENERS
    # ═══════════════════════════════════════════════════════════
    def open_camera_window(self):
        if self.camera_window.isVisible():
            self.camera_window.activateWindow()
        else:
            self.camera_window.show()

    def open_all_sky_window(self):
        if self.all_sky_window.isVisible():
            self.all_sky_window.activateWindow()
        else:
            self.all_sky_window.show()

    def open_gps_window(self):
        if self.gps_window.isVisible():
            self.gps_window.activateWindow()
        else:
            self.gps_window.show()

    # ═══════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════
    def reset_ui_status(self):
        for name in self.status_indicators:
            self._set_indicator(name, False)

    def closeEvent(self, event):
        # Stop control loops
        self.control_timer.stop()
        self.slow_timer.stop()

        # Stop simulation
        if self.sim_engine:
            self.sim_engine.stop()

        # Stop Alpaca server
        if self.alpaca_thread:
            self.alpaca_thread.stop()

        # Stop Telemetry server
        if hasattr(self, 'telemetry_server') and self.telemetry_server:
            self.telemetry_server.stop()

        # Stop workers
        self.telemetry_worker.stop()
        self.camera_worker.stop()
        self.weather_worker.stop()
        self.gps_worker.stop()

        # Disconnect hardware
        if self.control_serial:
            self.control_serial.close()
        self.science_driver.dispose()

        # Close sub-windows
        if self.camera_window:
            self.camera_window.close()
        if self.all_sky_window:
            self.all_sky_window.close()
        if self.gps_window:
            self.gps_window.close()

        event.accept()
