# stcs_v1/tests/mega_relay_tester.py
import sys
import time
import serial
import serial.tools.list_ports
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QComboBox, QLabel, 
                             QGroupBox, QGridLayout, QMessageBox)
from PyQt6.QtCore import QTimer, Qt

class MegaRelayTester(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arduino Mega 2560 Relay Diagnostics")
        self.resize(800, 600)
        self.serial_conn = None
        self.state = bytearray(7)
        self.heartbeat_timer = QTimer()
        self.heartbeat_timer.timeout.connect(self.send_packet)
        self.heartbeat_timer.setInterval(500)
        self.init_ui()
        self.apply_dark_theme()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        conn_group = QGroupBox("Arduino Mega 2560 Connection")
        conn_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.refresh_ports()
        conn_layout.addWidget(QLabel("COM Port:"))
        conn_layout.addWidget(self.port_combo)
        
        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        conn_layout.addWidget(self.btn_refresh)
        
        self.btn_connect = QPushButton("CONNECT")
        self.btn_connect.setCheckable(True)
        self.btn_connect.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.btn_connect)
        
        self.lbl_status = QLabel("Status: DISCONNECTED")
        self.lbl_status.setStyleSheet("color: #ff4444; font-weight: bold;")
        conn_layout.addWidget(self.lbl_status)
        conn_layout.addStretch()
        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)

        grids_layout = QHBoxLayout()
        
        # RA Group
        ra_group = QGroupBox("RA Module (Pins 22-29)")
        ra_grid = QGridLayout()
        self.add_momentary_btn(ra_grid, "RA Coarse E", 0, 0, 1, 0x08)
        self.add_momentary_btn(ra_grid, "RA Coarse W", 0, 1, 1, 0x04)
        self.add_momentary_btn(ra_grid, "RA Fine 1 E", 1, 0, 1, 0x02)
        self.add_momentary_btn(ra_grid, "RA Fine 1 W", 1, 1, 1, 0x01)
        self.add_momentary_btn(ra_grid, "RA Fine 2 E", 2, 0, 0, 0x08)
        self.add_momentary_btn(ra_grid, "RA Fine 2 W", 2, 1, 0, 0x04)
        self.add_momentary_btn(ra_grid, "Track ON",    3, 0, 0, 0x02)
        self.add_momentary_btn(ra_grid, "Track OFF",   3, 1, 0, 0x01)
        ra_group.setLayout(ra_grid)
        grids_layout.addWidget(ra_group)

        # DEC Group
        dec_group = QGroupBox("DEC Module (Pins 30-37)")
        dec_grid = QGridLayout()
        self.add_momentary_btn(dec_grid, "DEC Coarse N", 0, 0, 3, 0x08)
        self.add_momentary_btn(dec_grid, "DEC Coarse S", 0, 1, 3, 0x04)
        self.add_momentary_btn(dec_grid, "DEC Fine 1 N", 1, 0, 3, 0x02)
        self.add_momentary_btn(dec_grid, "DEC Fine 1 S", 1, 1, 3, 0x01)
        self.add_momentary_btn(dec_grid, "DEC Fine 2 N", 2, 0, 2, 0x08)
        self.add_momentary_btn(dec_grid, "DEC Fine 2 S", 2, 1, 2, 0x04)
        self.add_momentary_btn(dec_grid, "Dome CW",      3, 0, 4, 0x08)
        self.add_momentary_btn(dec_grid, "Dome CCW",     3, 1, 4, 0x04)
        dec_group.setLayout(dec_grid)
        grids_layout.addWidget(dec_group)

        # ACC Group
        acc_group = QGroupBox("Accessories (Pins 38-41)")
        acc_grid = QGridLayout()
        self.add_momentary_btn(acc_grid, "Focus IN",  0, 0, 5, 0x08)
        self.add_momentary_btn(acc_grid, "Focus OUT", 0, 1, 5, 0x04)
        self.add_momentary_btn(acc_grid, "Console ON",  1, 0, 6, 0x02)
        self.add_momentary_btn(acc_grid, "Console OFF", 1, 1, 6, 0x01)
        self.add_momentary_btn(acc_grid, "Dome Pwr ON",     2, 0, 6, 0x08)
        self.add_momentary_btn(acc_grid, "Dome Pwr OFF",    2, 1, 6, 0x04)
        acc_group.setLayout(acc_grid)
        grids_layout.addWidget(acc_group)

        main_layout.addLayout(grids_layout)

        footer_layout = QHBoxLayout()
        self.btn_estop = QPushButton("🛑 EMERGENCY STOP ALL")
        self.btn_estop.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; font-size: 16px; padding: 15px;")
        self.btn_estop.clicked.connect(self.stop_all)
        footer_layout.addWidget(self.btn_estop, 1)

        self.lbl_packet = QLabel("Current Packet: :U0000000#")
        self.lbl_packet.setStyleSheet("font-family: Consolas, monospace; font-size: 16px; background: #111; padding: 10px; border: 1px solid #555;")
        self.lbl_packet.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_layout.addWidget(self.lbl_packet, 2)

        main_layout.addLayout(footer_layout)
        self.enable_controls(False)

    def add_momentary_btn(self, layout, name, row, col, byte, bit):
        btn = QPushButton(name)
        btn.setMinimumHeight(40)
        btn.pressed.connect(lambda b=byte, m=bit: self.update_bit(b, m, True))
        btn.released.connect(lambda b=byte, m=bit: self.update_bit(b, m, False))
        layout.addWidget(btn, row, col)

    def refresh_ports(self):
        self.port_combo.clear()
        for port in serial.tools.list_ports.comports():
            self.port_combo.addItem(f"{port.device} - {port.description}", port.device)

    def toggle_connection(self):
        if self.btn_connect.isChecked():
            port = self.port_combo.currentData()
            if not port:
                self.btn_connect.setChecked(False)
                return
            try:
                # Open port and assert DTR to reset Arduino
                self.serial_conn = serial.Serial(port, 115200, timeout=1)
                
                # Prevent clicking while Arduino is booting up
                self.lbl_status.setText("Status: BOOTING ARDUINO (Wait 2s)...")
                self.lbl_status.setStyleSheet("color: #eab308; font-weight: bold;")
                QApplication.processEvents() # Force UI to update
                time.sleep(2.0) # WAIT 2 SECONDS FOR MEGA BOOTLOADER
                
                self.lbl_status.setText("Status: CONNECTED")
                self.lbl_status.setStyleSheet("color: #00cc00; font-weight: bold;")
                self.btn_connect.setText("DISCONNECT")
                self.enable_controls(True)
                
                # Start sending heartbeat *after* boot is finished
                self.heartbeat_timer.start()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to connect: {e}")
                self.btn_connect.setChecked(False)
        else:
            self.heartbeat_timer.stop()
            self.stop_all()
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
            self.lbl_status.setText("Status: DISCONNECTED")
            self.lbl_status.setStyleSheet("color: #ff4444; font-weight: bold;")
            self.btn_connect.setText("CONNECT")
            self.enable_controls(False)

    def enable_controls(self, enabled):
        for box in self.findChildren(QGroupBox):
            if "Module" in box.title() or "Accessories" in box.title():
                box.setEnabled(enabled)
        self.btn_estop.setEnabled(enabled)

    def update_bit(self, byte_idx, bitmask, active):
        if active: self.state[byte_idx] |= bitmask
        else:      self.state[byte_idx] &= ~bitmask
        self.send_packet()

    def stop_all(self):
        for i in range(7): self.state[i] = 0x00
        self.send_packet()

    def send_packet(self):
        packet = bytearray(b':U')
        
        # BYPASS CH340 DRIVER BUG:
        # Convert raw binary bits into safe ASCII characters to prevent 0x00 bytes from being dropped.
        for b in self.state:
            safe_ascii_byte = b | 0x30 # e.g., 0x08 becomes 0x38 (ASCII '8')
            packet.append(safe_ascii_byte)
            
        packet.extend(b'#')
        
        # Update UI to show the ASCII string being sent
        self.lbl_packet.setText(f"Current Packet: {packet.decode('ascii')}")
        
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.write(packet)
                self.serial_conn.flush()
            except Exception:
                self.btn_connect.click()

    def apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #1e1e1e; color: #ffffff; }
            QGroupBox { border: 2px solid #333; border-radius: 5px; margin-top: 10px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px 0 3px; }
            QPushButton { background-color: #3a3a3a; border: 1px solid #555; border-radius: 4px; padding: 5px; }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:pressed { background-color: #0288d1; }
            QPushButton:disabled { background-color: #222; color: #555; }
            QComboBox { background-color: #333; border: 1px solid #555; padding: 3px; color: white; }
        """)

    def closeEvent(self, a0):
        self.heartbeat_timer.stop()
        self.stop_all()
        if self.serial_conn and self.serial_conn.is_open: self.serial_conn.close()
        a0.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MegaRelayTester()
    window.show()
    sys.exit(app.exec())