# stcs_v1/src/ui/components/gps_panel.py
import math
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QGroupBox, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont

class SkyPlotWidget(QWidget):
    """Custom Radar/Polar plot to mimic Firebird's Satellite Sky View."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.satellites = []

    def update_data(self, satellites):
        self.satellites = satellites
        self.update() 

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        center = rect.center()
        radius = min(rect.width(), rect.height()) / 2 - 20
        
        # Draw Radar Background
        painter.setBrush(QBrush(QColor(20, 30, 40)))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        
        for r_factor in [1.0, 0.66, 0.33]:
            r = radius * r_factor
            painter.drawEllipse(center, r, r)
            
        painter.drawLine(int(center.x()), int(center.y() - radius), int(center.x()), int(center.y() + radius))
        painter.drawLine(int(center.x() - radius), int(center.y()), int(center.x() + radius), int(center.y()))
        
        painter.setPen(QPen(QColor(200, 200, 200)))
        font = QFont("Arial", 10, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(int(center.x() - 5), int(center.y() - radius - 5), "N")
        painter.drawText(int(center.x() + radius + 5), int(center.y() + 5), "E")
        painter.drawText(int(center.x() - 5), int(center.y() + radius + 15), "S")
        painter.drawText(int(center.x() - radius - 15), int(center.y() + 5), "W")

        # Draw Satellites
        for sat in self.satellites:
            el = sat.get("elevation", 0)
            az = sat.get("azimuth", 0)
            snr = sat.get("snr", 0)
            prn = sat.get("prn", "")
            
            r_sat = radius * (1.0 - (el / 90.0))
            angle_rad = math.radians(az - 90) 
            x = center.x() + r_sat * math.cos(angle_rad)
            y = center.y() + r_sat * math.sin(angle_rad)
            
            if snr > 35: color = QColor(0, 255, 0)
            elif snr > 20: color = QColor(255, 255, 0)
            else: color = QColor(255, 0, 0)
            
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawEllipse(int(x) - 8, int(y) - 8, 16, 16)
            
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(int(x) + 10, int(y) + 5, str(prn))


class SNRBarWidget(QWidget):
    """Custom Bar Chart to mimic Firebird's SNR Display."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 150)
        self.satellites = []

    def update_data(self, satellites):
        self.satellites = satellites
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        margin_bottom = 20
        max_snr = 50.0 
        
        if not self.satellites: return
        
        bar_width = (rect.width() / len(self.satellites)) - 5
        bar_width = min(bar_width, 30) 
        
        for i, sat in enumerate(self.satellites):
            snr = sat.get("snr", 0)
            prn = sat.get("prn", "")
            
            h = (snr / max_snr) * (rect.height() - margin_bottom)
            x = 10 + i * (bar_width + 5)
            y = rect.height() - margin_bottom - h
            
            if snr > 35: color = QColor(0, 255, 0)
            elif snr > 20: color = QColor(255, 255, 0)
            else: color = QColor(255, 0, 0)
            
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawRect(int(x), int(y), int(bar_width), int(h))
            
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(int(x), int(rect.height() - 5), str(prn))
            painter.drawText(int(x), int(y - 5), str(snr))


class GPSPanel(QWidget):
    """Main UI Component for the GPS Monitor embedded in the main window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Top Data Section
        data_group = QGroupBox("GNSS Position & Time")
        data_layout = QGridLayout()
        
        self.lbl_fix = QLabel("Hardware: Auto-Discovering...")
        self.lbl_lat = QLabel("Latitude: --")
        self.lbl_lon = QLabel("Longitude: --")
        self.lbl_alt = QLabel("Altitude: -- m")
        self.lbl_time = QLabel("UTC Time: --:--:--")
        self.lbl_speed = QLabel("Speed: -- knots")
        self.lbl_course = QLabel("Course: -- deg")
        
        font = QFont("Arial", 12, QFont.Weight.Bold)
        for lbl in [self.lbl_lat, self.lbl_lon, self.lbl_time, self.lbl_alt]:
            lbl.setFont(font)
            lbl.setStyleSheet("color: #00ffcc;")

        data_layout.addWidget(self.lbl_fix, 0, 0)
        data_layout.addWidget(self.lbl_time, 0, 1)
        data_layout.addWidget(self.lbl_lat, 1, 0)
        data_layout.addWidget(self.lbl_lon, 1, 1)
        data_layout.addWidget(self.lbl_alt, 1, 2)
        data_layout.addWidget(self.lbl_speed, 2, 0)
        data_layout.addWidget(self.lbl_course, 2, 1)
        data_group.setLayout(data_layout)
        main_layout.addWidget(data_group)

        # Visuals Section (Skyplot & SNR)
        visuals_layout = QHBoxLayout()
        
        sky_group = QGroupBox("Satellites in View (Skyplot)")
        sky_layout = QVBoxLayout()
        self.sky_plot = SkyPlotWidget()
        sky_layout.addWidget(self.sky_plot)
        sky_group.setLayout(sky_layout)
        
        snr_group = QGroupBox("Signal to Noise Ratio (dBHz)")
        snr_layout = QVBoxLayout()
        self.snr_bar = SNRBarWidget()
        snr_layout.addWidget(self.snr_bar)
        snr_group.setLayout(snr_layout)
        
        visuals_layout.addWidget(sky_group, stretch=1)
        visuals_layout.addWidget(snr_group, stretch=1)
        
        main_layout.addLayout(visuals_layout)

    @pyqtSlot(bool, str)
    def handle_connection(self, success, message):
        if success:
            self.lbl_fix.setText(f"Hardware: {message}")
            self.lbl_fix.setStyleSheet("color: #00ff00;")
        else:
            self.lbl_fix.setText(f"Hardware: {message}")
            self.lbl_fix.setStyleSheet("color: #ff0000;")

    @pyqtSlot(dict)
    def update_ui(self, data):
        fix_map = {0: "No Fix", 1: "3D Fix (GPS)", 2: "DGPS/SBAS Fix"}
        fix_text = fix_map.get(data.get("fix_quality", 0), "Unknown")
        
        current_hw_text = self.lbl_fix.text().split(" | ")[0] 
        self.lbl_fix.setText(f"{current_hw_text} | Fix Status: {fix_text}")
        
        if data.get("fix_quality", 0) > 0:
            self.lbl_lat.setText(f"Latitude: {data['latitude']:.6f}°")
            self.lbl_lon.setText(f"Longitude: {data['longitude']:.6f}°")
            self.lbl_alt.setText(f"Altitude: {data['altitude']:.1f} m")
            if data["utc_time"]:
                self.lbl_time.setText(f"UTC Time: {data['utc_time'].strftime('%H:%M:%S')}")
            self.lbl_speed.setText(f"Speed: {data['speed_knots']} kn")
            self.lbl_course.setText(f"Course: {data['course_true']}°")

        sats = data.get("satellite_details", [])
        self.sky_plot.update_data(sats)
        self.snr_bar.update_data(sats)