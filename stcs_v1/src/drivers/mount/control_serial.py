# src/drivers/mount/control_serial.py
"""
DUO Mega 2560 Relay Controller Serial Driver.

Manages the serial connection to the 4th Arduino (DUO Mega 2560)
which controls telescope motion relays. Sends the `:UXXXXXXX#`
protocol string at a configurable rate.

Protocol:
  Packet: :U<c_rah><c_ral><c_dech><c_decl><c_dome><c_acc><c_console>#
  Each byte is a 4-bit nibble OR'd with 0x30 to produce an ASCII char.
  Start marker: ':U' (0x3A, 0x55)
  End marker: '#' (0x23)
"""
import time
import logging
import threading
from src.drivers.mount.smart_serial import SmartSerial

logger = logging.getLogger("ControlSerial")


class ControlSerial:
    """
    Serial interface to the DUO Mega 2560 motion relay controller.
    
    Usage:
        cs = ControlSerial(serial_number="...", baud_rate=115200)
        cs.connect()
        cs.send_relay_packet(payload_bytes)  # 7 bytes
        cs.close()
    """

    def __init__(self, serial_number: str, baud_rate: int = 115200, timeout: int = 1):
        self.serial_number = serial_number
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.driver = None
        self.connected = False
        self.hardware_ready = False
        self._lock = threading.Lock()

    def connect(self):
        """Connect to the DUO Arduino by serial number."""
        try:
            self.driver = SmartSerial(
                self.serial_number,
                baud_rate=self.baud_rate,
                timeout=self.timeout
            )
            self.driver.connect()

            # The DUO is a write-heavy device (10Hz relay packets).
            # Use a short write_timeout to prevent blocking the UI thread indefinitely
            # if the USB connection becomes congested or unresponsive.
            self.driver.connection.write_timeout = 0.2

            # Wait for Arduino bootloader to finish
            logger.info("DUO Arduino connected. Waiting 2s for bootloader...")
            time.sleep(2)

            # Drain any bootloader output
            if self.driver.connection.in_waiting > 0:
                self.driver.connection.read(self.driver.connection.in_waiting)

            self.hardware_ready = True
            self.connected = True
            logger.info("DUO Arduino ready for commands.")
        except Exception as e:
            logger.error(f"DUO Arduino connection failed: {e}")
            self.connected = False
            self.hardware_ready = False
            raise

    def send_relay_packet(self, payload: bytes):
        """
        Sends a 7-byte relay payload as the :UXXXXXXX# protocol string.
        
        Args:
            payload: 7 bytes [c_rah, c_ral, c_dech, c_decl, c_dome, c_acc, c_console]
                     Each byte is a raw nibble (0x00-0x0F).
        """
        if not self.connected or not self.hardware_ready:
            return
        if not self.driver or not self.driver.connection or not self.driver.connection.is_open:
            return
        if len(payload) != 7:
            logger.error(f"Invalid payload length: {len(payload)}, expected 7")
            return

        with self._lock:
            try:
                # Drain echo data to prevent USB CDC backpressure.
                # Use read() to actually consume the bytes, not just reset.
                conn = self.driver.connection
                if conn.in_waiting > 0:
                    conn.read(conn.in_waiting)

                # Build packet: :U + 7 encoded nibbles + #
                packet = bytearray(b':U')
                for b in payload:
                    packet.append((b & 0x0F) | 0x30)
                packet.extend(b'#')

                conn.write(packet)
                # NOTE: No flush() — write() pushes data to the OS buffer,
                # which handles 10-byte packets at 10Hz without issue.
                # flush() was causing Write Timeout exceptions because it
                # blocks until data is physically sent via USB, and with
                # multiple USB-serial devices, the USB bus can be busy.

            except Exception as e:
                logger.error(f"DUO Serial write error: {e}")

    def close(self):
        """Close the serial connection."""
        self.hardware_ready = False
        self.connected = False
        if self.driver:
            # Send all-zeros to clear relays before disconnecting
            try:
                self.send_relay_packet(bytes(7))
            except Exception:
                pass
            self.driver.close()
            logger.info("DUO Arduino connection closed.")
