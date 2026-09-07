# src/ui/components/camera/acquisition_section.py
from PyQt6.QtWidgets import (QWidget, QGridLayout, QVBoxLayout, QLabel, 
                             QLineEdit, QComboBox, QSpinBox, QCheckBox, 
                             QGroupBox, QMessageBox)
from PyQt6.QtCore import QTimer

class AcquisitionSection(QWidget):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.debounce_exp = QTimer()
        self.debounce_exp.setSingleShot(True)
        self.debounce_exp.setInterval(800)
        self.debounce_exp.timeout.connect(self.on_exp_changed)
        self.init_ui()

    def init_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)
        
        # Row 0: Exposure
        self.input_exp = QLineEdit("1.0")
        self.input_exp.textChanged.connect(lambda: self.debounce_exp.start())
        layout.addWidget(QLabel("Exposure (sec):"), 0, 0)
        layout.addWidget(self.input_exp, 0, 1)
        
        # Row 1: Shutter Mode
        self.combo_shutter = QComboBox()
        self.combo_shutter.addItems(["Normal", "Always Closed", "Always Open"])
        self.combo_shutter.activated.connect(lambda: self.worker.queue_set_shutter(self.combo_shutter.currentText()))
        layout.addWidget(QLabel("Shutter Mode:"), 1, 0)
        layout.addWidget(self.combo_shutter, 1, 1)
        
        # Row 2: Analog Gain
        self.combo_gain = QComboBox()
        self.combo_gain.addItems(["Medium","High", "Low"])
        self.combo_gain.activated.connect(lambda: self.worker.queue_set_gain(self.combo_gain.currentText()))
        layout.addWidget(QLabel("Analog Gain:"), 2, 0)
        layout.addWidget(self.combo_gain, 2, 1)
        
        # Row 3: ADC Speed
        self.combo_speed = QComboBox()
        self.combo_speed.addItems(["2 MHz","100 kHz"])
        self.combo_speed.activated.connect(lambda: self.worker.queue_set_speed(self.combo_speed.currentText()))
        layout.addWidget(QLabel("ADC Speed:"), 3, 0)
        layout.addWidget(self.combo_speed, 3, 1)

        # Row 4: Frames to Save (AcquisitionFramesToStore)
        self.spin_frames = QSpinBox()
        self.spin_frames.setRange(1, 10000)
        self.spin_frames.setValue(1)
        self.spin_frames.setToolTip("Number of frames to acquire and save in a single run")
        self.spin_frames.valueChanged.connect(lambda: self.worker.queue_set_frames_to_save(self.spin_frames.value()))
        layout.addWidget(QLabel("Frames to Save:"), 4, 0)
        layout.addWidget(self.spin_frames, 4, 1)

        # Row 5: Time Stamping Group (Matches LightField logic)
        self.group_stamps = QGroupBox("Time Stamping")
        stamps_layout = QVBoxLayout(self.group_stamps)
        
        self.chk_stamp_start = QCheckBox("Exposure Started")
        self.chk_stamp_end = QCheckBox("Exposure Ended")
        
        self.chk_stamp_start.clicked.connect(self.on_stamps_changed)
        self.chk_stamp_end.clicked.connect(self.on_stamps_changed)
        
        stamps_layout.addWidget(self.chk_stamp_start)
        stamps_layout.addWidget(self.chk_stamp_end)
        
        layout.addWidget(self.group_stamps, 5, 0, 1, 2)

        # Row 6: Frame Tracking (AcquisitionFrameTrackingEnabled)
        self.chk_frame_tracking = QCheckBox("Frame Tracking")
        self.chk_frame_tracking.setToolTip("Attaches an incrementing identification number to each frame")
        self.chk_frame_tracking.setChecked(False) # Default as per LightField
        self.chk_frame_tracking.clicked.connect(lambda: self.worker.queue_set_frame_tracking(self.chk_frame_tracking.isChecked()))
        layout.addWidget(self.chk_frame_tracking, 6, 0, 1, 2)

    def on_stamps_changed(self):
        """Calculates bitmask for AcquisitionTimeStampingStamps Flags enum."""
        mask = 0
        if self.chk_stamp_start.isChecked(): mask |= 1
        if self.chk_stamp_end.isChecked(): mask |= 2
        self.worker.queue_set_time_stamps(mask)

    def update_shutter_options(self, readout_mode):
        """Dynamic Shutter validation logic based on Readout Mode."""
        current_shutter = self.combo_shutter.currentText()
        self.combo_shutter.blockSignals(True)
        self.combo_shutter.clear()

        if readout_mode == "Kinetics":
            options = ["Always Closed", "Always Open", "Open Before Trigger"]
            self.combo_shutter.addItems(options)
            if current_shutter == "Normal":
                QMessageBox.warning(self, "Invalid Shutter Mode", 
                                  "Shutter Mode 'Normal' is invalid for Kinetics Readout.\n"
                                  "Switching to 'Always Closed'.")
                self.combo_shutter.setCurrentText("Always Closed")
            elif current_shutter in options:
                self.combo_shutter.setCurrentText(current_shutter)
            else:
                self.combo_shutter.setCurrentText("Always Closed")
        else:
            options = ["Normal", "Always Closed", "Always Open"]
            self.combo_shutter.addItems(options)
            if current_shutter == "Open Before Trigger":
                self.combo_shutter.setCurrentText("Normal")
            elif current_shutter in options:
                self.combo_shutter.setCurrentText(current_shutter)
            else:
                self.combo_shutter.setCurrentText("Normal")

        self.combo_shutter.blockSignals(False)
        self.worker.queue_set_shutter(self.combo_shutter.currentText())

    def on_exp_changed(self):
        try: 
            self.worker.queue_set_exposure(float(self.input_exp.text()))
        except ValueError: 
            pass
    
    def get_exposure(self):
        try: 
            return float(self.input_exp.text())
        except ValueError: 
            return 1.0
        
    def sync_ui(self):
        # Trigger updates to backend
        self.on_exp_changed()
        self.worker.queue_set_shutter(self.combo_shutter.currentText())
        self.worker.queue_set_gain(self.combo_gain.currentText())
        self.worker.queue_set_speed(self.combo_speed.currentText())
        self.worker.queue_set_frames_to_save(self.spin_frames.value())
        self.on_stamps_changed()
        self.worker.queue_set_frame_tracking(self.chk_frame_tracking.isChecked())