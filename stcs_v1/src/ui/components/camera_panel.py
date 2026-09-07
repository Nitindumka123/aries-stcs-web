# src/ui/components/camera_panel.py
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QLabel, QLineEdit, QPushButton, QComboBox, 
                             QGridLayout, QSizePolicy)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QPixmap

class CameraPanel(QWidget):
    """
    UI Component for Science Camera.
    Includes Polling Timer for Temperature.
    """
    def __init__(self, camera_worker):
        super().__init__()
        self.worker = camera_worker
        self.init_ui()
        self.connect_signals()
        
        # Temp Polling Timer (5 seconds)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.request_temp_update)
        # Timer starts only when connected
        
    def init_ui(self):
        layout = QHBoxLayout(self)
        
        # --- LEFT COLUMN ---
        controls_layout = QVBoxLayout()
        
        # 1. Status
        conn_group = QGroupBox("Status")
        conn_grid = QGridLayout()
        self.btn_connect = QPushButton("Connect Camera")
        self.btn_connect.setStyleSheet("background-color: #2e7d32; font-weight: bold; color: white;")
        self.btn_connect.clicked.connect(self.on_connect_click)
        conn_grid.addWidget(self.btn_connect, 0, 0, 1, 2)
        
        self.lbl_status = QLabel("DISCONNECTED")
        self.lbl_status.setStyleSheet("color: #777; font-weight: bold;")
        conn_grid.addWidget(QLabel("State:"), 1, 0)
        conn_grid.addWidget(self.lbl_status, 1, 1)
        
        self.lbl_temp = QLabel("-- C")
        self.lbl_temp.setStyleSheet("color: #4488ff; font-weight: bold; font-size: 14px;")
        conn_grid.addWidget(QLabel("Sensor Temp:"), 2, 0)
        conn_grid.addWidget(self.lbl_temp, 2, 1)
        conn_group.setLayout(conn_grid)
        controls_layout.addWidget(conn_group)
        
        # 2. Settings
        settings_group = QGroupBox("Acquisition Settings")
        settings_grid = QGridLayout()
        
        self.input_exp = QLineEdit("1.0")
        settings_grid.addWidget(QLabel("Exposure (s):"), 0, 0)
        settings_grid.addWidget(self.input_exp, 0, 1)
        
        self.combo_bin = QComboBox()
        self.combo_bin.addItems(["1x1", "2x2", "4x4"])
        settings_grid.addWidget(QLabel("Binning:"), 1, 0)
        settings_grid.addWidget(self.combo_bin, 1, 1)
        
        self.input_fname = QLineEdit("Target_001")
        settings_grid.addWidget(QLabel("File Prefix:"), 2, 0)
        settings_grid.addWidget(self.input_fname, 2, 1)
        settings_group.setLayout(settings_grid)
        controls_layout.addWidget(settings_group)
        
        # 3. Cooling
        cool_group = QGroupBox("Cooling")
        cool_layout = QHBoxLayout()
        self.input_setpoint = QLineEdit("-70")
        self.input_setpoint.setFixedWidth(50)
        btn_set_temp = QPushButton("Set")
        btn_set_temp.clicked.connect(self.on_set_temp_click)
        cool_layout.addWidget(QLabel("Target:"))
        cool_layout.addWidget(self.input_setpoint)
        cool_layout.addWidget(QLabel("C"))
        cool_layout.addWidget(btn_set_temp)
        cool_group.setLayout(cool_layout)
        controls_layout.addWidget(cool_group)
        
        # 4. Acquire Button
        self.btn_acquire = QPushButton("ACQUIRE FRAME")
        self.btn_acquire.setMinimumHeight(50)
        self.btn_acquire.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; font-size: 14px;")
        self.btn_acquire.clicked.connect(self.on_acquire_click)
        self.btn_acquire.setEnabled(False)
        controls_layout.addWidget(self.btn_acquire)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout, 1) 
        
        # --- RIGHT COLUMN (Preview) ---
        preview_group = QGroupBox("Image Preview")
        preview_layout = QVBoxLayout()
        self.lbl_preview = QLabel("No Image")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("background-color: #000; border: 1px solid #333;")
        self.lbl_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lbl_preview.setMinimumSize(400, 400)
        preview_layout.addWidget(self.lbl_preview)
        preview_group.setLayout(preview_layout)
        
        layout.addWidget(preview_group, 3) 
    
    def connect_signals(self):
        self.worker.connection_status.connect(self.handle_connection)
        self.worker.image_ready.connect(self.handle_preview)
        self.worker.temperature_updated.connect(self.update_temp_display)

    def request_temp_update(self):
        self.worker.queue_poll_temp()

    # --- SLOTS ---
    def on_connect_click(self):
        self.btn_connect.setText("Connecting...")
        self.btn_connect.setEnabled(False)
        self.worker.queue_connect()

    def on_set_temp_click(self):
        try:
            t = float(self.input_setpoint.text())
            self.worker.queue_set_temp(t)
        except ValueError:
            pass

    def on_acquire_click(self):
        try:
            settings = {
                'exposure': float(self.input_exp.text()),
                'binning': int(self.combo_bin.currentText()[0]),
                'filename': self.input_fname.text()
            }
            self.lbl_status.setText("ACQUIRING...")
            self.lbl_status.setStyleSheet("color: #eab308; font-weight: bold;")
            self.btn_acquire.setEnabled(False)
            self.worker.queue_acquire(settings)
        except ValueError:
            self.lbl_status.setText("Invalid Input")

    @pyqtSlot(bool, str)
    def handle_connection(self, success, msg):
        if success:
            self.lbl_status.setText("ONLINE")
            self.lbl_status.setStyleSheet("color: #43a047; font-weight: bold;")
            self.btn_connect.setText("Connected")
            self.btn_acquire.setEnabled(True)
            self.poll_timer.start(5000) # Start polling temp every 5s
        else:
            self.lbl_status.setText("OFFLINE")
            self.lbl_status.setStyleSheet("color: #d32f2f; font-weight: bold;")
            self.btn_connect.setText("Connect Camera")
            self.btn_connect.setEnabled(True)
            self.poll_timer.stop()
            self.lbl_temp.setText("-- C")

    @pyqtSlot(str)
    def handle_preview(self, image_path):
        self.lbl_status.setText("IDLE")
        self.lbl_status.setStyleSheet("color: #777; font-weight: bold;")
        self.btn_acquire.setEnabled(True)
        
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            w = self.lbl_preview.width()
            h = self.lbl_preview.height()
            self.lbl_preview.setPixmap(pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.lbl_preview.setText(f"Failed to load: {image_path}")

    @pyqtSlot(float)
    def update_temp_display(self, temp):
        self.lbl_temp.setText(f"{temp:.1f} C")