# src/ui/windows/camera_window.py
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGroupBox, QFrame, QScrollArea, QSizePolicy, QToolButton, QLabel)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QPixmap

# Import Components
from src.ui.components.camera.status_section import StatusSection
from src.ui.components.camera.acquisition_section import AcquisitionSection
from src.ui.components.camera.roi_section import RoiSection
from src.ui.components.camera.readout_section import ReadoutSection
from src.ui.components.camera.file_save_section import FileSaveSection
from src.ui.components.camera.control_footer import ControlFooter
from src.ui.components.camera.trigger_section import TriggerInSection, TriggerOutSection

class CameraControlWindow(QMainWindow):
    def __init__(self, camera_worker):
        super().__init__()
        self.worker = camera_worker
        self.setWindowTitle("Science Camera Controller - PIXIS 512B")
        self.resize(1200, 950)
        
        self.setStyleSheet("""
            QGroupBox { font-weight: bold; margin-top: 10px; border: 1px solid #444; border-radius: 4px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLabel { font-size: 13px; }
            QToolButton { background-color: #333; color: white; border: 1px solid #555; border-radius: 2px; padding: 5px; text-align: left; font-weight: bold; }
            QToolButton:hover { background-color: #444; }
            QToolButton:checked { background-color: #0d47a1; }
        """)

        self.init_ui()
        
        # Poll Status
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.worker.queue_poll_temp)
        
        self.worker.connection_status.connect(self.on_connection)
        self.worker.image_ready.connect(self.handle_image)

        # CONNECT VALIDATION SIGNAL
        self.readout_section.mode_changed.connect(self.handle_readout_mode_validation)

        self.set_ui_enabled(False)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        sidebar = QWidget()
        sidebar.setFixedWidth(420)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0,0,0,0); side_layout.setSpacing(5)

        self.status_section = StatusSection(self.worker)
        side_layout.addWidget(self.status_section)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(5,5,15,5); self.scroll_layout.setSpacing(10)

        self.acq_section = AcquisitionSection(self.worker)
        self.trig_in_section = TriggerInSection(self.worker)
        self.trig_out_section = TriggerOutSection(self.worker)
        self.readout_section = ReadoutSection(self.worker)
        self.roi_section = RoiSection(self.worker)
        self.file_section = FileSaveSection(self.worker)
        
        self.add_accordion("Acquisition Settings", self.acq_section)
        self.add_accordion("Trigger In", self.trig_in_section)
        self.add_accordion("Trigger Out", self.trig_out_section)
        self.add_accordion("Readout Control", self.readout_section)
        self.add_accordion("Region of Interest", self.roi_section)
        self.add_accordion("File Save Settings", self.file_section)
        
        self.scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        side_layout.addWidget(scroll)

        self.footer = ControlFooter(self.worker)
        self.footer.btn_acquire.clicked.connect(self.on_acquire)
        side_layout.addWidget(self.footer)

        main_layout.addWidget(sidebar)

        right_grp = QGroupBox("Live Preview")
        r_layout = QVBoxLayout()
        self.lbl_preview = QLabel("No Image Data")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("background-color: black;")
        self.lbl_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        r_layout.addWidget(self.lbl_preview)
        right_grp.setLayout(r_layout)
        main_layout.addWidget(right_grp)

    def add_accordion(self, title, widget):
        btn = QToolButton()
        btn.setText(f"▼ {title}")
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        widget.setVisible(False)
        def toggle(checked):
            widget.setVisible(checked)
            btn.setText(f"{'▲' if checked else '▼'} {title}")
        btn.toggled.connect(toggle)
        self.scroll_layout.addWidget(btn)
        self.scroll_layout.addWidget(widget)

    def set_ui_enabled(self, enabled):
        self.acq_section.setEnabled(enabled)
        self.trig_in_section.setEnabled(enabled)
        self.trig_out_section.setEnabled(enabled)
        self.readout_section.setEnabled(enabled)
        self.roi_section.setEnabled(enabled)
        self.file_section.setEnabled(enabled)
        self.footer.setEnabled(enabled)

    @pyqtSlot(str)
    def handle_readout_mode_validation(self, mode):
        """Cross-component validation triggered when Readout Mode changes."""
        self.acq_section.update_shutter_options(mode)
        self.trig_in_section.update_trigger_options(mode)

    @pyqtSlot(bool, str)
    def on_connection(self, success, msg):
        if success:
            self.set_ui_enabled(True)
            self.poll_timer.start(5000)
            QTimer.singleShot(500, self.sync_all)
        else:
            self.set_ui_enabled(False)
            self.poll_timer.stop()

    def sync_all(self):
        self.acq_section.sync_ui()
        self.trig_in_section.sync_ui()
        self.trig_out_section.sync_ui()
        self.readout_section.sync_ui()
        self.roi_section.sync_ui()
        self.file_section.sync_ui()
        self.footer.sync_ui()

    def on_acquire(self):
        exp = self.acq_section.get_exposure()
        self.worker.queue_acquire({'exposure': exp})

    @pyqtSlot(str)
    def handle_image(self, path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            w, h = self.lbl_preview.width(), self.lbl_preview.height()
            self.lbl_preview.setPixmap(pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio))

    def closeEvent(self, event):
        self.poll_timer.stop()
        event.accept()