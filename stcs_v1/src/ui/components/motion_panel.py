# src/ui/components/motion_panel.py
"""
Redesigned Telescope Motion Control Panel.

Features:
  - Independent RA and DEC speed selectors (Coarse / Fine 1 / Fine 2)
  - D-Pad arrows with hold-to-move (press=start, release=stop)
  - Tracking ON/OFF buttons (one-shot pulse signals)
  - Dome CW / CCW / OFF buttons (one-shot pulse, toggle behavior)
  - Manual coordinate slew (GOTO TARGET) with waypoint planner
  - Emergency stop

Safety Interlocks:
  - RA East/West mutually exclusive (enforced by MotionState)
  - DEC North/South mutually exclusive
  - Dome CW/CCW mutually exclusive; OFF cancels both
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QLabel, QLineEdit, QPushButton, QGridLayout,
                             QMessageBox, QButtonGroup, QSizePolicy, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer


class HoldButton(QPushButton):
    """
    A button that emits signals on press (hold) and release.
    Used for RA/DEC direction control where telescope moves
    only while the button is held down.
    """
    held = pyqtSignal()
    released_signal = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.held.emit()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.released_signal.emit()


class SpeedButton(QPushButton):
    """Radio-style toggle button for speed selection."""

    def __init__(self, text, speed_key, parent=None):
        super().__init__(text, parent)
        self.speed_key = speed_key
        self.setCheckable(True)
        self.setMinimumHeight(32)


class MotionPanel(QWidget):
    """
    Self-contained UI component for Telescope Motion Control.
    Emits signals for actions the parent window handles.
    """
    # Signals
    slew_requested = pyqtSignal(str, str)     # ra_str, dec_str
    park_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    jog_requested = pyqtSignal(str)           # direction (N, S, E, W)

    # Per-axis offset signals → user enters ACTUAL position, system computes correction
    set_ra_offset_requested = pyqtSignal(str)    # actual RA (HMS string)
    set_dec_offset_requested = pyqtSignal(str)   # actual DEC (DMS string)
    set_dome_offset_requested = pyqtSignal(str)  # actual Dome AZ (degrees string)
    clear_offsets_requested = pyqtSignal()

    # Manual DEC homing signal
    set_dec_home_requested = pyqtSignal(str)     # DEC home value (DMS string)

    # New motion signals → wired to MotionState by MainWindow
    ra_speed_changed = pyqtSignal(str)        # COARSE / FINE_1 / FINE_2
    dec_speed_changed = pyqtSignal(str)
    ra_direction_changed = pyqtSignal(str)    # EAST / WEST / NONE
    dec_direction_changed = pyqtSignal(str)   # NORTH / SOUTH / NONE
    track_on_requested = pyqtSignal()
    track_off_requested = pyqtSignal()
    dome_cw_requested = pyqtSignal()
    dome_ccw_requested = pyqtSignal()
    dome_off_requested = pyqtSignal()

    def __init__(self, worker=None):
        super().__init__()
        self.worker = worker
        self._last_tracking_state = None
        self._last_dome_state = None

        # Direction reversal interlock: opposing button disabled for N seconds
        # after release to protect motors from instant direction reversal.
        self.DIRECTION_INTERLOCK_MS = 3000  # 3 seconds

        # D-Pad button references (set in init_ui)
        self.btn_north = None
        self.btn_south = None
        self.btn_east = None
        self.btn_west = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ════════════════════════════════════════════
        # 1. SPEED SELECTION + D-PAD SECTION
        # ════════════════════════════════════════════
        motion_group = QGroupBox("Manual Motion Control")
        motion_layout = QHBoxLayout()

        # ── LEFT: DEC Speed (Vertical) ──
        dec_speed_group = QGroupBox("DEC Speed")
        dec_speed_layout = QVBoxLayout()
        dec_speed_layout.setSpacing(4)

        self.dec_speed_buttons = QButtonGroup(self)
        self.dec_speed_buttons.setExclusive(True)

        for label, key in [("● Coarse", "COARSE"), ("● Fine 1", "FINE_1"), ("● Fine 2", "FINE_2")]:
            btn = SpeedButton(label, key)
            btn.setStyleSheet(self._speed_btn_style())
            self.dec_speed_buttons.addButton(btn)
            dec_speed_layout.addWidget(btn)
            if key == "COARSE":
                btn.setChecked(True)

        self.dec_speed_buttons.buttonClicked.connect(self._on_dec_speed_clicked)
        dec_speed_group.setLayout(dec_speed_layout)
        motion_layout.addWidget(dec_speed_group)

        # ── CENTER: D-PAD & RA Speed ──
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(10)

        # RA Speed row (Without GroupBox to save height)
        ra_speed_widget = QWidget()
        ra_speed_layout = QHBoxLayout(ra_speed_widget)
        ra_speed_layout.setContentsMargins(0, 5, 0, 0)
        ra_speed_layout.setSpacing(6)

        lbl_ra = QLabel("RA Speed:")
        lbl_ra.setStyleSheet("color: #b0bec5; font-weight: bold; font-size: 13px;")
        ra_speed_layout.addWidget(lbl_ra)

        self.ra_speed_buttons = QButtonGroup(self)
        self.ra_speed_buttons.setExclusive(True)

        for label, key in [("● Coarse", "COARSE"), ("● Fine 1", "FINE_1"), ("● Fine 2", "FINE_2")]:
            btn = SpeedButton(label, key)
            btn.setStyleSheet(self._speed_btn_style())
            self.ra_speed_buttons.addButton(btn)
            ra_speed_layout.addWidget(btn)
            if key == "COARSE":
                btn.setChecked(True)

        self.ra_speed_buttons.buttonClicked.connect(self._on_ra_speed_clicked)
        center_layout.addWidget(ra_speed_widget, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Arrow buttons D-PAD
        dpad_widget = QWidget()
        dpad_layout = QGridLayout(dpad_widget)
        dpad_layout.setSpacing(4)

        self.btn_north = self._create_arrow_btn("▲\nn", "NORTH")
        self.btn_south = self._create_arrow_btn("▼\ns", "SOUTH")
        self.btn_west = self._create_arrow_btn("◀\nw", "WEST")
        self.btn_east = self._create_arrow_btn("▶\ne", "EAST")

        # Store opposing pairs for interlock logic
        self._opposing_buttons = {
            "NORTH": self.btn_south,
            "SOUTH": self.btn_north,
            "EAST":  self.btn_west,
            "WEST":  self.btn_east,
        }

        # Center label
        center_lbl = QLabel("✦")
        center_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_lbl.setStyleSheet("font-size: 20px; color: #4488ff;")

        dpad_layout.addWidget(self.btn_north, 0, 1, Qt.AlignmentFlag.AlignCenter)
        dpad_layout.addWidget(self.btn_west, 1, 0, Qt.AlignmentFlag.AlignRight)
        dpad_layout.addWidget(center_lbl, 1, 1, Qt.AlignmentFlag.AlignCenter)
        dpad_layout.addWidget(self.btn_east, 1, 2, Qt.AlignmentFlag.AlignLeft)
        dpad_layout.addWidget(self.btn_south, 2, 1, Qt.AlignmentFlag.AlignCenter)

        dpad_layout.setColumnStretch(0, 1)
        dpad_layout.setColumnStretch(2, 1)

        center_layout.addWidget(dpad_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        motion_layout.addWidget(center_widget, stretch=2)
        motion_group.setLayout(motion_layout)
        layout.addWidget(motion_group)

        # ════════════════════════════════════════════
        # 2. TRACKING & DOME CONTROL
        # ════════════════════════════════════════════
        control_row = QHBoxLayout()

        # ── Tracking ──
        track_group = QGroupBox("Tracking (Sidereal Drive)")
        track_layout = QHBoxLayout()

        self.btn_track_on = QPushButton("🟢 TRACK ON")
        self.btn_track_on.setFixedHeight(38)
        self.btn_track_on.setStyleSheet(
            "background-color: #1b5e20; color: #a5d6a7; font-weight: bold; "
            "border: 2px solid #2e7d32; border-radius: 4px;"
        )
        self.btn_track_on.clicked.connect(self._on_track_on)

        self.btn_track_off = QPushButton("🔴 TRACK OFF")
        self.btn_track_off.setFixedHeight(38)
        self.btn_track_off.setStyleSheet(
            "background-color: #4a1919; color: #ef9a9a; font-weight: bold; "
            "border: 2px solid #c62828; border-radius: 4px;"
        )
        self.btn_track_off.clicked.connect(self._on_track_off)

        self.lbl_track_status = QLabel("● OFF")
        self.lbl_track_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_track_status.setStyleSheet("color: #ef5350; font-weight: bold; font-size: 13px;")

        track_layout.addWidget(self.btn_track_on)
        track_layout.addWidget(self.btn_track_off)
        track_layout.addWidget(self.lbl_track_status)
        track_group.setLayout(track_layout)
        control_row.addWidget(track_group)

        # ── Dome Control ──
        dome_group = QGroupBox("Dome Control")
        dome_layout = QHBoxLayout()

        self.btn_dome_cw = QPushButton("↻ CW")
        self.btn_dome_cw.setFixedHeight(38)
        self.btn_dome_cw.setCheckable(True)
        self.btn_dome_cw.setStyleSheet(self._dome_btn_style(False))
        self.btn_dome_cw.clicked.connect(self._on_dome_cw)

        self.btn_dome_ccw = QPushButton("↺ CCW")
        self.btn_dome_ccw.setFixedHeight(38)
        self.btn_dome_ccw.setCheckable(True)
        self.btn_dome_ccw.setStyleSheet(self._dome_btn_style(False))
        self.btn_dome_ccw.clicked.connect(self._on_dome_ccw)

        self.btn_dome_off = QPushButton("■ STOP")
        self.btn_dome_off.setFixedHeight(38)
        self.btn_dome_off.setStyleSheet(
            "background-color: #b71c1c; color: white; font-weight: bold; "
            "border-radius: 4px;"
        )
        self.btn_dome_off.clicked.connect(self._on_dome_off)

        dome_layout.addWidget(self.btn_dome_cw)
        dome_layout.addWidget(self.btn_dome_ccw)
        dome_layout.addWidget(self.btn_dome_off)
        dome_group.setLayout(dome_layout)
        control_row.addWidget(dome_group)

        layout.addLayout(control_row)

        # ════════════════════════════════════════════
        # 3. COORDINATES & CALIBRATION (merged DEC Home + Target Coords)
        # ════════════════════════════════════════════
        target_group = QGroupBox("Coordinates & Calibration")
        target_grid = QGridLayout()
        target_grid.setVerticalSpacing(6)

        # ── Row 0: DEC Manual Home (calibration row) ──
        lbl_home = QLabel("DEC Home:")
        lbl_home.setStyleSheet("color: #a7ffeb; font-weight: bold; font-size: 12px;")
        target_grid.addWidget(lbl_home, 0, 0)

        self.input_dec_home = QLineEdit()
        self.input_dec_home.setPlaceholderText("+DD:MM:SS")
        self.input_dec_home.setStyleSheet(
            "background-color: #1a1a2e; color: #e0e0e0; border: 1px solid #444; "
            "border-radius: 4px; padding: 4px 8px; font-size: 13px; "
            "font-family: 'Consolas', monospace;"
        )
        target_grid.addWidget(self.input_dec_home, 0, 1)

        home_action_widget = QWidget()
        home_action_layout = QHBoxLayout(home_action_widget)
        home_action_layout.setContentsMargins(0, 0, 0, 0)
        home_action_layout.setSpacing(6)

        self.btn_set_dec_home = QPushButton("🏠 SET HOME")
        self.btn_set_dec_home.setFixedHeight(30)
        self.btn_set_dec_home.setStyleSheet(
            "background-color: #00695c; color: #a7ffeb; font-weight: bold; "
            "border: 2px solid #00897b; border-radius: 4px; padding: 2px 8px;"
        )
        self.btn_set_dec_home.setToolTip(
            "Read the DEC value from the telescope's mechanical dials\n"
            "and enter it here. The system will calibrate the encoder\n"
            "offset so the display matches the dial reading."
        )
        self.btn_set_dec_home.clicked.connect(
            lambda: self.set_dec_home_requested.emit(self.input_dec_home.text())
        )
        home_action_layout.addWidget(self.btn_set_dec_home)

        self.lbl_home_status = QLabel("● NOT SET")
        self.lbl_home_status.setStyleSheet(
            "color: #ef5350; font-weight: bold; font-size: 11px;"
        )
        home_action_layout.addWidget(self.lbl_home_status)
        target_grid.addWidget(home_action_widget, 0, 2)

        # ── Separator line ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a4a4a; margin: 2px 0;")
        target_grid.addWidget(sep, 1, 0, 1, 3)

        # ── Row 2-4: Target Coordinate offsets ──
        self.input_ra = QLineEdit("00:00:00")
        target_grid.addWidget(QLabel("RA (HMS):"), 2, 0)
        target_grid.addWidget(self.input_ra, 2, 1)

        self.input_dec = QLineEdit("+00:00:00")
        target_grid.addWidget(QLabel("DEC (DMS):"), 3, 0)
        target_grid.addWidget(self.input_dec, 3, 1)

        self.input_dome = QLineEdit("0.0")
        target_grid.addWidget(QLabel("Dome AZ (°):"), 4, 0)
        target_grid.addWidget(self.input_dome, 4, 1)

        # Per-axis SET OFFSET buttons
        set_btn_style = (
            "background-color: #f9a825; color: black; font-weight: bold; "
            "border-radius: 4px; padding: 4px 8px;"
        )
        set_btn_tooltip = (
            "Enter the ACTUAL (true) position of the centered star.\n"
            "The system will compute and store the offset automatically."
        )

        self.btn_set_ra = QPushButton("SET RA")
        self.btn_set_ra.setStyleSheet(set_btn_style)
        self.btn_set_ra.setToolTip(set_btn_tooltip)
        self.btn_set_ra.clicked.connect(lambda: self.set_ra_offset_requested.emit(self.input_ra.text()))
        target_grid.addWidget(self.btn_set_ra, 2, 2)

        self.btn_set_dec = QPushButton("SET DEC")
        self.btn_set_dec.setStyleSheet(set_btn_style)
        self.btn_set_dec.setToolTip(set_btn_tooltip)
        self.btn_set_dec.clicked.connect(lambda: self.set_dec_offset_requested.emit(self.input_dec.text()))
        target_grid.addWidget(self.btn_set_dec, 3, 2)

        self.btn_set_dome = QPushButton("SET DOME")
        self.btn_set_dome.setStyleSheet(set_btn_style)
        self.btn_set_dome.setToolTip(set_btn_tooltip)
        self.btn_set_dome.clicked.connect(lambda: self.set_dome_offset_requested.emit(self.input_dome.text()))
        target_grid.addWidget(self.btn_set_dome, 4, 2)

        target_group.setLayout(target_grid)
        layout.addWidget(target_group)

        # Offset status label (shows current active corrections)
        self.lbl_offset_status = QLabel("Offsets: RA 0\" | DEC 0\" | Dome 0\"")
        self.lbl_offset_status.setStyleSheet(
            "color: #78909c; font-size: 11px; padding: 2px 4px;"
        )
        self.lbl_offset_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_offset_status)

        # Action buttons
        action_layout = QHBoxLayout()

        self.btn_slew = QPushButton("GOTO TARGET")
        self.btn_slew.setFixedHeight(42)
        self.btn_slew.setStyleSheet(
            "background-color: #0277bd; color: white; font-weight: bold; "
            "font-size: 14px; border-radius: 4px;"
        )
        self.btn_slew.clicked.connect(self.on_slew_click)
        action_layout.addWidget(self.btn_slew)

        self.btn_clear_offsets = QPushButton("CLEAR OFFSETS")
        self.btn_clear_offsets.setFixedHeight(42)
        self.btn_clear_offsets.setStyleSheet(
            "background-color: #455a64; color: #cfd8dc; font-weight: bold; "
            "border-radius: 4px;"
        )
        self.btn_clear_offsets.setToolTip("Reset all RA, DEC, and Dome offset corrections to zero.")
        self.btn_clear_offsets.clicked.connect(self._on_clear_offsets)
        action_layout.addWidget(self.btn_clear_offsets)

        self.btn_stop = QPushButton("🛑 EMERGENCY STOP")
        self.btn_stop.setFixedHeight(42)
        self.btn_stop.setStyleSheet(
            "background-color: #c62828; color: white; font-weight: bold; "
            "font-size: 14px; border-radius: 4px; border: 2px solid #e53935;"
        )
        self.btn_stop.clicked.connect(self.on_stop_click)
        action_layout.addWidget(self.btn_stop)

        self.btn_park = QPushButton("🅿 PARK")
        self.btn_park.setFixedHeight(42)
        self.btn_park.setStyleSheet(
            "background-color: #4527a0; color: white; font-weight: bold; "
            "font-size: 14px; border-radius: 4px;"
        )
        self.btn_park.clicked.connect(self.on_park_click)
        action_layout.addWidget(self.btn_park)

        layout.addLayout(action_layout)
        layout.addStretch()

    # ─── FACTORY METHODS ─────────────────────────────────────────

    def _create_arrow_btn(self, text, direction):
        """Create a hold-to-move arrow button with direction reversal interlock."""
        btn = HoldButton(text)
        btn.setFixedSize(QSize(42, 42))
        btn.setStyleSheet(
            "font-size: 12px; font-weight: bold; padding: 2px; "
            "background-color: #263238; color: #b0bec5; "
            "border: 2px solid #37474f; border-radius: 8px;"
        )

        if direction in ("EAST", "WEST"):
            btn.held.connect(lambda d=direction: self._on_direction_press(d))
            btn.released_signal.connect(lambda d=direction: self._on_direction_release(d))
        else:
            btn.held.connect(lambda d=direction: self._on_direction_press(d))
            btn.released_signal.connect(lambda d=direction: self._on_direction_release(d))

        return btn

    def _on_direction_press(self, direction):
        """Handle direction button press: emit signal to start motion."""
        if direction in ("EAST", "WEST"):
            self.ra_direction_changed.emit(direction)
        else:
            self.dec_direction_changed.emit(direction)

    def _on_direction_release(self, direction):
        """
        Handle direction button release:
        1. Emit NONE to stop motion.
        2. Disable the opposing direction button for DIRECTION_INTERLOCK_MS.
        """
        # Stop motion
        if direction in ("EAST", "WEST"):
            self.ra_direction_changed.emit("NONE")
        else:
            self.dec_direction_changed.emit("NONE")

        # Disable opposing button and re-enable after delay
        opposing_btn = self._opposing_buttons.get(direction)
        if opposing_btn:
            opposing_btn.setEnabled(False)
            opposing_btn.setStyleSheet(
                "font-size: 12px; font-weight: bold; padding: 2px; "
                "background-color: #1a1a1a; color: #555555; "
                "border: 2px solid #333333; border-radius: 8px;"
            )
            # Re-enable after delay
            QTimer.singleShot(
                self.DIRECTION_INTERLOCK_MS,
                lambda b=opposing_btn: self._re_enable_direction_btn(b)
            )

    def _re_enable_direction_btn(self, btn):
        """Re-enable a direction button after the interlock delay."""
        btn.setEnabled(True)
        btn.setStyleSheet(
            "font-size: 12px; font-weight: bold; padding: 2px; "
            "background-color: #263238; color: #b0bec5; "
            "border: 2px solid #37474f; border-radius: 8px;"
        )

    def _speed_btn_style(self):
        return (
            "QPushButton { background-color: #1a1a2e; color: #8888aa; "
            "border: 1px solid #333; border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
            "QPushButton:checked { background-color: #1a237e; color: #82b1ff; "
            "border: 2px solid #5c6bc0; font-weight: bold; }"
        )

    def _dome_btn_style(self, active):
        if active:
            return (
                "background-color: #0d47a1; color: #82b1ff; font-weight: bold; "
                "border: 2px solid #42a5f5; border-radius: 4px;"
            )
        return (
            "background-color: #1a1a2e; color: #8888aa; font-weight: bold; "
            "border: 1px solid #333; border-radius: 4px;"
        )

    # ─── SIGNAL HANDLERS ─────────────────────────────────────────

    def _on_ra_speed_clicked(self, btn):
        self.ra_speed_changed.emit(btn.speed_key)

    def _on_dec_speed_clicked(self, btn):
        self.dec_speed_changed.emit(btn.speed_key)

    def _on_track_on(self):
        self.track_on_requested.emit()
        self.lbl_track_status.setText("● ON")
        self.lbl_track_status.setStyleSheet("color: #66bb6a; font-weight: bold; font-size: 13px;")

    def _on_track_off(self):
        self.track_off_requested.emit()
        self.lbl_track_status.setText("● OFF")
        self.lbl_track_status.setStyleSheet("color: #ef5350; font-weight: bold; font-size: 13px;")

    def _on_dome_cw(self):
        self.btn_dome_cw.setChecked(True)
        self.btn_dome_ccw.setChecked(False)
        self.btn_dome_cw.setStyleSheet(self._dome_btn_style(True))
        self.btn_dome_ccw.setStyleSheet(self._dome_btn_style(False))
        self.dome_cw_requested.emit()

    def _on_dome_ccw(self):
        self.btn_dome_ccw.setChecked(True)
        self.btn_dome_cw.setChecked(False)
        self.btn_dome_ccw.setStyleSheet(self._dome_btn_style(True))
        self.btn_dome_cw.setStyleSheet(self._dome_btn_style(False))
        self.dome_ccw_requested.emit()

    def _on_dome_off(self):
        self.btn_dome_cw.setChecked(False)
        self.btn_dome_ccw.setChecked(False)
        self.btn_dome_cw.setStyleSheet(self._dome_btn_style(False))
        self.btn_dome_ccw.setStyleSheet(self._dome_btn_style(False))
        self.dome_off_requested.emit()

    # ─── EXISTING ACTION HANDLERS ────────────────────────────────

    def on_slew_click(self):
        ra = self.input_ra.text()
        dec = self.input_dec.text()
        self.slew_requested.emit(ra, dec)

    def on_park_click(self):
        confirm = QMessageBox.question(
            self, "Confirm Park",
            "Are you sure you want to PARK the telescope?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.park_requested.emit()

    def on_stop_click(self):
        self._on_dome_off()  # Also visually reset dome buttons
        self.stop_requested.emit()

    def _on_clear_offsets(self):
        """Clear all stored offsets after confirmation."""
        confirm = QMessageBox.question(
            self, "Clear Offsets",
            "Reset ALL offset corrections (RA, DEC, Dome) to zero?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.clear_offsets_requested.emit()

    def parse_dms_to_deg(self, dms_str):
        try:
            if ':' in dms_str:
                parts = dms_str.split(':')
                d = float(parts[0])
                m = float(parts[1]) if len(parts) > 1 else 0
                s = float(parts[2]) if len(parts) > 2 else 0
                sign = -1 if dms_str.strip().startswith('-') else 1
                return sign * (abs(d) + m / 60 + s / 3600)
            else:
                return float(dms_str)
        except Exception:
            raise ValueError("Bad DMS format")

    # ─── PUBLIC UPDATE METHOD ────────────────────────────────────

    def update_from_state(self, status: dict):
        """Update visual indicators from MotionState snapshot."""
        tracking = status.get("tracking", False)
        if tracking != self._last_tracking_state:
            self._last_tracking_state = tracking
            if tracking:
                self.lbl_track_status.setText("● ON")
                self.lbl_track_status.setStyleSheet("color: #66bb6a; font-weight: bold; font-size: 13px;")
            else:
                self.lbl_track_status.setText("● OFF")
                self.lbl_track_status.setStyleSheet("color: #ef5350; font-weight: bold; font-size: 13px;")

        dome = status.get("dome_state", "OFF")
        if dome != self._last_dome_state:
            self._last_dome_state = dome
            self.btn_dome_cw.setChecked(dome == "CW")
            self.btn_dome_ccw.setChecked(dome == "CCW")
            self.btn_dome_cw.setStyleSheet(self._dome_btn_style(dome == "CW"))
            self.btn_dome_ccw.setStyleSheet(self._dome_btn_style(dome == "CCW"))

    def update_home_status(self, home_deg):
        """Update the DEC home status indicator and prefill the input field."""
        if home_deg is not None:
            self.lbl_home_status.setText("● HOME SET")
            self.lbl_home_status.setStyleSheet(
                "color: #66bb6a; font-weight: bold; font-size: 12px; padding: 0 6px;"
            )
            # Prefill the input with the persisted value in DMS
            from src.core.legacy_decoder import LegacyDecoder
            dms = LegacyDecoder.decimal_deg_to_dms(home_deg)
            self.input_dec_home.setText(dms)
        else:
            self.lbl_home_status.setText("● NOT SET")
            self.lbl_home_status.setStyleSheet(
                "color: #ef5350; font-weight: bold; font-size: 12px; padding: 0 6px;"
            )
            self.input_dec_home.clear()