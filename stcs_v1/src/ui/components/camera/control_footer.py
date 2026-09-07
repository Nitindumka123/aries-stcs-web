from PyQt6.QtWidgets import QGroupBox, QGridLayout, QLabel, QLineEdit, QPushButton
from PyQt6.QtCore import QTimer

class ControlFooter(QGroupBox):
    def __init__(self, worker):
        super().__init__() # No title
        self.setStyleSheet("QGroupBox { border: 1px solid #444; border-radius: 4px; background-color: #222; }")
        self.worker = worker
        self.debounce = QTimer(); self.debounce.setSingleShot(True); self.debounce.setInterval(800)
        self.debounce.timeout.connect(self.on_temp_change)
        self.init_ui()

    def init_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(10,10,10,10)
        
        self.input_setpoint = QLineEdit("-70.0")
        self.input_setpoint.textChanged.connect(lambda: self.debounce.start())
        btn_set = QPushButton("Set Temp"); btn_set.clicked.connect(self.on_temp_change)
        layout.addWidget(QLabel("Target C:"), 0, 0)
        layout.addWidget(self.input_setpoint, 0, 1)
        layout.addWidget(btn_set, 0, 2)
        
        self.btn_acquire = QPushButton("ACQUIRE IMAGE")
        self.btn_acquire.setMinimumHeight(50)
        self.btn_acquire.setStyleSheet("background-color: #0288d1; color: white; font-weight: bold; font-size: 16px; border-radius: 6px;")
        layout.addWidget(self.btn_acquire, 1, 0, 1, 3)

    def on_temp_change(self):
        try: self.worker.queue_set_temp(float(self.input_setpoint.text()))
        except: pass
    
    def sync_ui(self):
        self.on_temp_change()