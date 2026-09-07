# src/ui/components/camera/readout_section.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QComboBox, QSpinBox, QDoubleSpinBox
from PyQt6.QtCore import pyqtSlot, pyqtSignal

class ReadoutSection(QWidget):
    # Signal emitted to notify other components of a readout mode change
    mode_changed = pyqtSignal(str)

    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.worker.readout_status_updated.connect(self.update_status)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5,5,5,5)
        
        # Mode
        grid = QGridLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Full Frame", "Kinetics"])
        self.combo_mode.activated.connect(self.on_mode_changed)
        grid.addWidget(QLabel("Mode:"), 0, 0); grid.addWidget(self.combo_mode, 0, 1)
        
        self.lbl_time = QLabel("0.0 ms")
        self.lbl_time.setStyleSheet("color: #4488ff; font-weight: bold;")
        grid.addWidget(QLabel("Readout Time:"), 1, 0); grid.addWidget(self.lbl_time, 1, 1)
        layout.addLayout(grid)
        
        # Kinetics Specifics (Container)
        self.kinetics_group = QWidget()
        k_layout = QGridLayout(self.kinetics_group)
        k_layout.setContentsMargins(0,5,0,0)
        
        self.sb_height = QSpinBox(); self.sb_height.setRange(1, 512); self.sb_height.setValue(100)
        self.sb_height.valueChanged.connect(lambda: self.worker.queue_set_kinetics_height(self.sb_height.value()))
        
        self.combo_shift = QComboBox()
        shift_rates = [
            "3.2", "6.2", "9.2", "12.2", "15.2", "18.2", "21.2", "24.2", 
            "27.2", "30.2", "33.2", "36.2", "39.2", "42.2", "45.2", "48.2"
        ]
        self.combo_shift.addItems(shift_rates)
        self.combo_shift.setEditable(False)
        self.combo_shift.activated.connect(lambda: self.worker.queue_set_shift_rate(float(self.combo_shift.currentText())))
        
        self.lbl_frames = QLabel("0")
        self.lbl_fps = QLabel("0.0")
        
        k_layout.addWidget(QLabel("Win Height:"), 0, 0); k_layout.addWidget(self.sb_height, 0, 1)
        k_layout.addWidget(QLabel("Shift (us):"), 1, 0); k_layout.addWidget(self.combo_shift, 1, 1)
        k_layout.addWidget(QLabel("Frames/Read:"), 2, 0); k_layout.addWidget(self.lbl_frames, 2, 1)
        k_layout.addWidget(QLabel("Est FPS:"), 3, 0); k_layout.addWidget(self.lbl_fps, 3, 1)
        
        layout.addWidget(self.kinetics_group)
        self.kinetics_group.hide()

    def on_mode_changed(self):
        mode = self.combo_mode.currentText()
        self.worker.queue_set_readout_mode(mode)
        
        if mode == "Kinetics":
            self.kinetics_group.show()
        else:
            self.kinetics_group.hide()
            
        # Emit signal to trigger validations in Acquisition and Trigger sections
        self.mode_changed.emit(mode)

    @pyqtSlot(dict)
    def update_status(self, data):
        self.lbl_time.setText(f"{data.get('time_ms', 0):.2f} ms")
        self.lbl_frames.setText(str(data.get('frames_per', 0)))
        self.lbl_fps.setText(f"{data.get('fps', 0):.2f}")

    def sync_ui(self):
        self.on_mode_changed()