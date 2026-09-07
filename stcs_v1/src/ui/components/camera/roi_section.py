from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QStackedWidget, QGridLayout, QSpinBox, QPushButton, QMessageBox

class RoiSection(QWidget):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5,5,5,5)
        
        top = QHBoxLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Full Sensor", "Binned Sensor", "Line Sensor", "Custom Regions"])
        self.combo_mode.activated.connect(self.on_mode_changed)
        top.addWidget(QLabel("Mode:")); top.addWidget(self.combo_mode)
        layout.addLayout(top)
        
        self.combo_prov = QComboBox()
        self.combo_prov.addItems(["Hardware", "Software"])
        self.combo_prov.activated.connect(lambda: self.worker.queue_set_provider(self.combo_prov.currentText()))
        layout.addWidget(QLabel("Binning Provider:")); layout.addWidget(self.combo_prov)
        
        self.stack = QStackedWidget()
        self.stack.addWidget(QWidget()) # Full
        
        # Binned
        pg_bin = QWidget(); l_bin = QGridLayout(pg_bin); l_bin.setContentsMargins(0,0,0,0)
        self.sb_bx = QSpinBox(); self.sb_bx.setRange(1,128)
        self.sb_by = QSpinBox(); self.sb_by.setRange(1,128)
        btn_bin = QPushButton("Set"); btn_bin.clicked.connect(self.on_set_bin)
        l_bin.addWidget(QLabel("X:"),0,0); l_bin.addWidget(self.sb_bx,0,1)
        l_bin.addWidget(QLabel("Y:"),1,0); l_bin.addWidget(self.sb_by,1,1)
        l_bin.addWidget(btn_bin,2,0,1,2)
        self.stack.addWidget(pg_bin)
        
        # Line
        pg_line = QWidget(); l_line = QGridLayout(pg_line); l_line.setContentsMargins(0,0,0,0)
        self.sb_rows = QSpinBox(); self.sb_rows.setRange(1,512)
        btn_line = QPushButton("Set"); btn_line.clicked.connect(lambda: self.worker.queue_set_line_params(self.sb_rows.value()))
        l_line.addWidget(QLabel("Rows:"),0,0); l_line.addWidget(self.sb_rows,0,1); l_line.addWidget(btn_line,1,0,1,2)
        self.stack.addWidget(pg_line)
        
        # Custom
        pg_cust = QWidget(); l_cust = QGridLayout(pg_cust); l_cust.setContentsMargins(0,0,0,0)
        self.sb_x = QSpinBox(); self.sb_x.setRange(0,511)
        self.sb_y = QSpinBox(); self.sb_y.setRange(0,511)
        self.sb_w = QSpinBox(); self.sb_w.setRange(1,512); self.sb_w.setValue(512)
        self.sb_h = QSpinBox(); self.sb_h.setRange(1,512); self.sb_h.setValue(512)
        self.sb_cbx = QSpinBox(); self.sb_cbx.setRange(1,16)
        self.sb_cby = QSpinBox(); self.sb_cby.setRange(1,16)
        btn_cust = QPushButton("Set ROI"); btn_cust.clicked.connect(self.on_set_cust)
        l_cust.addWidget(QLabel("X:"),0,0); l_cust.addWidget(self.sb_x,0,1)
        l_cust.addWidget(QLabel("Y:"),0,2); l_cust.addWidget(self.sb_y,0,3)
        l_cust.addWidget(QLabel("W:"),1,0); l_cust.addWidget(self.sb_w,1,1)
        l_cust.addWidget(QLabel("H:"),1,2); l_cust.addWidget(self.sb_h,1,3)
        l_cust.addWidget(QLabel("BX:"),2,0); l_cust.addWidget(self.sb_cbx,2,1)
        l_cust.addWidget(QLabel("BY:"),2,2); l_cust.addWidget(self.sb_cby,2,3)
        l_cust.addWidget(btn_cust,3,0,1,4)
        self.stack.addWidget(pg_cust)
        
        layout.addWidget(self.stack)

    def on_mode_changed(self):
        self.stack.setCurrentIndex(self.combo_mode.currentIndex())
        self.worker.queue_set_roi(self.combo_mode.currentText())

    def on_set_bin(self):
        self.worker.queue_set_bin_params((self.sb_bx.value(), self.sb_by.value()))

    def on_set_cust(self):
        # Basic validation
        if (self.sb_x.value() + self.sb_w.value() > 512) or (self.sb_y.value() + self.sb_h.value() > 512):
            QMessageBox.warning(self, "Error", "ROI out of bounds")
            return
        self.worker.queue_set_custom_roi((self.sb_x.value(), self.sb_y.value(), self.sb_w.value(), self.sb_h.value(), self.sb_cbx.value(), self.sb_cby.value()))

    def sync_ui(self):
        self.on_mode_changed()
        self.worker.queue_set_provider(self.combo_prov.currentText())