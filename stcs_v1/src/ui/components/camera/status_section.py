from PyQt6.QtWidgets import QGroupBox, QGridLayout, QPushButton, QLabel
from PyQt6.QtCore import pyqtSlot

class StatusSection(QGroupBox):
    def __init__(self, worker):
        super().__init__("System Status")
        self.worker = worker
        self.init_ui()
        self.worker.connection_status.connect(self.on_connection_status)
        self.worker.temperature_updated.connect(self.on_temp_update)

    def init_ui(self):
        layout = QGridLayout(self)
        self.btn_connect = QPushButton("Connect LightField")
        self.btn_connect.setStyleSheet("background-color: #2e7d32; color: white; padding: 8px;")
        self.btn_connect.clicked.connect(self.on_connect_click)
        
        self.lbl_status = QLabel("DISCONNECTED")
        self.lbl_status.setStyleSheet("color: red; font-weight: bold;")
        self.lbl_temp = QLabel("--.- C")
        self.lbl_temp.setStyleSheet("color: #4488ff; font-weight: bold; font-size: 16px;")
        
        layout.addWidget(self.btn_connect, 0, 0, 1, 2)
        layout.addWidget(QLabel("State:"), 1, 0); layout.addWidget(self.lbl_status, 1, 1)
        layout.addWidget(QLabel("Sensor Temp:"), 2, 0); layout.addWidget(self.lbl_temp, 2, 1)

    def on_connect_click(self):
        self.btn_connect.setText("Connecting...")
        self.btn_connect.setEnabled(False)
        self.worker.queue_connect()

    @pyqtSlot(bool, str)
    def on_connection_status(self, success, msg):
        if success:
            self.lbl_status.setText("ONLINE")
            self.lbl_status.setStyleSheet("color: #43a047;")
            self.btn_connect.setText("Connected")
        else:
            self.lbl_status.setText("OFFLINE")
            self.lbl_status.setStyleSheet("color: red;")
            self.btn_connect.setText("Connect")
            self.btn_connect.setEnabled(True)

    @pyqtSlot(float)
    def on_temp_update(self, val):
        self.lbl_temp.setText(f"{val:.1f} C")