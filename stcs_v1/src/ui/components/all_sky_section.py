import os
import time
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QGroupBox, QFileDialog, 
                             QCheckBox, QSpinBox)
from PyQt6.QtCore import QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QPixmap
import requests

class AllSkySection(QWidget):
    """
    Widget for displaying All Sky Camera feed.
    Supports:
    1. Local File Mode: Watches a specific file (e.g., 'latest.jpg')
    2. HTTP Mode: Fetches an image from a URL.
    """
    def __init__(self):
        super().__init__()
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_image)
        self.current_image_path = ""
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # --- Controls Group ---
        ctrl_grp = QGroupBox("All Sky Camera Settings")
        ctrl_layout = QHBoxLayout()
        
        self.input_source = QLineEdit("http://192.168.1.100/image.jpg")
        self.input_source.setPlaceholderText("File Path or URL")
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self.browse_file)
        
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 3600)
        self.spin_interval.setValue(10)
        self.spin_interval.setSuffix(" s")
        
        self.btn_toggle = QPushButton("START")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setStyleSheet("background-color: #2e7d32; font-weight: bold; color: white;")
        self.btn_toggle.clicked.connect(self.toggle_monitoring)
        
        ctrl_layout.addWidget(QLabel("Source:"))
        ctrl_layout.addWidget(self.input_source)
        ctrl_layout.addWidget(btn_browse)
        ctrl_layout.addWidget(QLabel("Refresh:"))
        ctrl_layout.addWidget(self.spin_interval)
        ctrl_layout.addWidget(self.btn_toggle)
        
        ctrl_grp.setLayout(ctrl_layout)
        layout.addWidget(ctrl_grp)
        
        # --- Image Display ---
        self.lbl_display = QLabel("All Sky Feed Offline")
        self.lbl_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_display.setStyleSheet("background-color: black; border: 2px solid #444; color: #888;")
        self.lbl_display.setMinimumHeight(400)
        layout.addWidget(self.lbl_display)
        
        # --- Info Footer ---
        self.lbl_info = QLabel("Last Update: Never")
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.lbl_info)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Image Source", "", "Images (*.jpg *.png)")
        if path:
            self.input_source.setText(path)

    def toggle_monitoring(self):
        if self.btn_toggle.isChecked():
            self.btn_toggle.setText("STOP")
            self.btn_toggle.setStyleSheet("background-color: #d32f2f; font-weight: bold; color: white;")
            self.refresh_image() # Immediate update
            self.refresh_timer.start(self.spin_interval.value() * 1000)
        else:
            self.btn_toggle.setText("START")
            self.btn_toggle.setStyleSheet("background-color: #2e7d32; font-weight: bold; color: white;")
            self.refresh_timer.stop()
            self.lbl_display.setText("Monitoring Stopped")

    def refresh_image(self):
        source = self.input_source.text().strip()
        pixmap = QPixmap()
        
        try:
            # Mode 1: HTTP URL
            if source.startswith("http"):
                try:
                    response = requests.get(source, timeout=3)
                    if response.status_code == 200:
                        pixmap.loadFromData(response.content)
                    else:
                        self.lbl_info.setText(f"Error: HTTP {response.status_code}")
                except Exception as e:
                    self.lbl_info.setText(f"Network Error: {str(e)}")
            
            # Mode 2: Local File
            elif os.path.exists(source):
                pixmap.load(source)
            
            # Mode 3: Invalid
            else:
                self.lbl_info.setText("Error: Source not found")

            # Update Display
            if not pixmap.isNull():
                w = self.lbl_display.width()
                h = self.lbl_display.height()
                self.lbl_display.setPixmap(pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio))
                self.lbl_info.setText(f"Last Update: {time.strftime('%H:%M:%S')}")
            
        except Exception as e:
            print(f"AllSky Error: {e}")