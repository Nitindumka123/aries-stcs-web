import json
import socket
import logging
from PyQt6.QtCore import QObject, pyqtSlot

# Configure logging
logger = logging.getLogger("UdpBroadcaster")

class UdpBroadcaster(QObject):
    """
    Listens to internal Qt signals and broadcasts them as JSON over UDP.
    target_port: Port for the mobile app to listen on (default 5005).
    """
    def __init__(self, target_port=5005):
        super().__init__()
        self.target_port = target_port
        self.broadcast_ip = '<broadcast>'
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        
        # Enable Broadcast
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Reuse address to prevent binding locks
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        logger.info(f"UDP Broadcaster initialized on port {self.target_port}")

    def _send_packet(self, category, payload):
        """Wraps data in a standard envelope and sends it."""
        try:
            packet = {
                "type": category,
                "data": payload
            }
            message = json.dumps(packet).encode('utf-8')
            self.sock.sendto(message, (self.broadcast_ip, self.target_port))
        except Exception as e:
            logger.error(f"Failed to broadcast UDP: {e}")

    @pyqtSlot(dict)
    def handle_telemetry(self, data):
        """
        Relays Mount Telemetry (RA, DEC, Dome, LST, etc.)
        Expected keys: 'ra_hms', 'dec_dms', 'dome_az', 'lst_hms', etc.
        """
        self._send_packet("telemetry", data)

    @pyqtSlot(dict)
    def handle_weather(self, data):
        """
        Relays Weather Data
        Expected keys: 'temp_c', 'humidity_percent', etc.
        """
        self._send_packet("weather", data)

    @pyqtSlot(float)
    def handle_camera_temp(self, temp):
        """Relays Camera Temperature"""
        self._send_packet("camera_status", {"temp": temp})

    @pyqtSlot(bool, str)
    def handle_camera_connection(self, connected, msg):
        """Relays Camera Connection State"""
        self._send_packet("camera_connection", {"connected": connected, "message": msg})