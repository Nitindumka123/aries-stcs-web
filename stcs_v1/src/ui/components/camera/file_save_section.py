# src/ui/components/camera/file_save_section.py
from PyQt6.QtWidgets import (QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, 
                             QCheckBox, QComboBox, QSpinBox, QFileDialog, QFrame)
from PyQt6.QtCore import QTimer, pyqtSlot, Qt
import os

class FileSaveSection(QWidget):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        
        # Debounce for text inputs to avoid flooding the IPC pipe
        self.debounce = QTimer()
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(800)
        self.debounce.timeout.connect(lambda: self.worker.queue_set_filename(self.input_name.text()))
        
        self.worker.example_filename_updated.connect(self.update_example)
        self.init_ui()

    def init_ui(self):
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(8)
        
        row = 0

        # --- Base File Name ---
        self.layout.addWidget(QLabel("Base File Name:"), row, 0)
        self.input_name = QLineEdit("Target")
        self.input_name.setToolTip("The base name before any prefixes or suffixes")
        self.input_name.textChanged.connect(lambda: self.debounce.start())
        self.layout.addWidget(self.input_name, row, 1, 1, 2)
        row += 1

        # --- File Path (Directory) ---
        self.layout.addWidget(QLabel("Save Folder:"), row, 0)
        self.input_dir = QLineEdit(os.path.join(os.getcwd(), "data"))
        self.input_dir.setReadOnly(True)
        btn_dir = QPushButton("Browse")
        btn_dir.setFixedWidth(70)
        btn_dir.clicked.connect(self.browse)
        self.layout.addWidget(self.input_dir, row, 1)
        self.layout.addWidget(btn_dir, row, 2)
        row += 1

        # --- Separator ---
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setFrameShadow(QFrame.Shadow.Sunken)
        self.layout.addWidget(line, row, 0, 1, 3)
        row += 1

        # --- Add Date ---
        self.chk_date = QCheckBox("Add Date")
        self.chk_date.clicked.connect(self.toggle_date_options)
        self.layout.addWidget(self.chk_date, row, 0)
        
        self.combo_date_fmt = QComboBox()
        self.combo_date_fmt.addItems([
            "yyyy_mm_dd", "yyyy_Month_dd", "dd_mm_yyyy", 
            "dd_Month_yyyy", "mm_dd_yyyy", "Month_dd_yyyy"
        ])
        self.combo_date_fmt.currentTextChanged.connect(self.update_date_fmt)
        self.combo_date_fmt.setVisible(False)
        self.layout.addWidget(self.combo_date_fmt, row, 1, 1, 2)
        row += 1

        # --- Add Time ---
        self.chk_time = QCheckBox("Add Time")
        self.chk_time.clicked.connect(self.toggle_time_options)
        self.layout.addWidget(self.chk_time, row, 0)
        
        self.combo_time_fmt = QComboBox()
        self.combo_time_fmt.addItems(["hh_mm_ss_24hr", "hh_mm_ss_ampm"])
        self.combo_time_fmt.currentTextChanged.connect(self.update_time_fmt)
        self.combo_time_fmt.setVisible(False)
        self.layout.addWidget(self.combo_time_fmt, row, 1, 1, 2)
        row += 1

        # --- Increment ---
        self.chk_inc = QCheckBox("Increment Name")
        self.chk_inc.clicked.connect(self.toggle_inc_options)
        self.layout.addWidget(self.chk_inc, row, 0)
        
        # Sub-container for increment details
        self.inc_container = QWidget()
        inc_layout = QGridLayout(self.inc_container)
        inc_layout.setContentsMargins(0, 0, 0, 0)
        
        self.sb_inc_start = QSpinBox(); self.sb_inc_start.setRange(0, 999999); self.sb_inc_start.setValue(1)
        self.sb_inc_start.valueChanged.connect(lambda v: self.worker.queue_set_inc_num(v))
        
        self.sb_inc_digits = QSpinBox(); self.sb_inc_digits.setRange(1, 12); self.sb_inc_digits.setValue(3)
        self.sb_inc_digits.valueChanged.connect(lambda v: self.worker.queue_set_inc_digits(v))
        
        inc_layout.addWidget(QLabel("Start:"), 0, 0); inc_layout.addWidget(self.sb_inc_start, 0, 1)
        inc_layout.addWidget(QLabel("Digits:"), 0, 2); inc_layout.addWidget(self.sb_inc_digits, 0, 3)
        
        self.inc_container.setVisible(False)
        self.layout.addWidget(self.inc_container, row, 1, 1, 2)
        row += 1

        # --- Example Filename Display ---
        self.lbl_ex = QLabel("Example: ...")
        self.lbl_ex.setStyleSheet("color: #4488ff; font-style: italic; font-weight: bold; background: #111; padding: 5px; border-radius: 3px;")
        self.lbl_ex.setWordWrap(True)
        self.layout.addWidget(self.lbl_ex, row, 0, 1, 3)

    def toggle_date_options(self):
        enabled = self.chk_date.isChecked()
        self.combo_date_fmt.setVisible(enabled)
        self.worker.queue_set_attach_date(enabled)
        if enabled: self.update_date_fmt()

    def toggle_time_options(self):
        enabled = self.chk_time.isChecked()
        self.combo_time_fmt.setVisible(enabled)
        self.worker.queue_set_attach_time(enabled)
        if enabled: self.update_time_fmt()

    def toggle_inc_options(self):
        enabled = self.chk_inc.isChecked()
        self.inc_container.setVisible(enabled)
        self.worker.queue_set_attach_increment(enabled)
        if enabled:
            self.worker.queue_set_inc_num(self.sb_inc_start.value())
            self.worker.queue_set_inc_digits(self.sb_inc_digits.value())

    def update_date_fmt(self):
        self.worker.queue_set_date_fmt(self.combo_date_fmt.currentText())

    def update_time_fmt(self):
        self.worker.queue_set_time_fmt(self.combo_time_fmt.currentText())

    def browse(self):
        p = QFileDialog.getExistingDirectory(self, "Select Save Directory", self.input_dir.text())
        if p:
            self.input_dir.setText(p)
            self.worker.queue_set_directory(p)

    @pyqtSlot(str)
    def update_example(self, txt):
        self.lbl_ex.setText(f"Preview: {txt}")

    def sync_ui(self):
        """Called on window load to push initial UI state to the hardware."""
        self.worker.queue_set_filename(self.input_name.text())
        self.worker.queue_set_directory(self.input_dir.text())
        self.toggle_date_options()
        self.toggle_time_options()
        self.toggle_inc_options()