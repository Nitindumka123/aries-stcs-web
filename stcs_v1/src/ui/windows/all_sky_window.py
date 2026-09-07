from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget
from src.ui.components.all_sky_section import AllSkySection

class AllSkyWindow(QMainWindow):
    """
    Dedicated Window for All Sky Camera Monitoring.
    Wraps the AllSkySection component.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("All Sky Camera Monitor")
        self.resize(800, 700)
        
        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Add the All Sky Component
        self.all_sky_panel = AllSkySection()
        layout.addWidget(self.all_sky_panel)

    def closeEvent(self, event):
        # Stop monitoring when window is closed to save resources
        if self.all_sky_panel.btn_toggle.isChecked():
            self.all_sky_panel.btn_toggle.click() # Toggle off
        event.accept()