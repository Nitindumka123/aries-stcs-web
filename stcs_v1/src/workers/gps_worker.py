# stcs_v1/src/workers/gps_worker.py
import time
import logging
from PyQt6.QtCore import QThread, pyqtSignal
import serial
from src.drivers.gps.gps_driver import GPSDriver
from src.core.gps_event_logger import GPSEventLogger

logger = logging.getLogger("GPSWorker")

# Data timeout threshold (seconds without valid NMEA data)
DATA_TIMEOUT_SECONDS = 5.0


class GPSWorker(QThread):
    """
    Background thread to poll the LOCOSYS GPS continuously.
    Prevents the 115200bps serial read from freezing the PyQt6 UI.
    Includes event logging for failures, data gaps, and anomalies.
    """
    gps_data_updated = pyqtSignal(dict)
    connection_status = pyqtSignal(bool, str)

    def __init__(self, port="AUTO"):
        super().__init__()
        self.driver = GPSDriver(port=port, baudrate=115200)
        self.running = False

        # Event Logger
        self.event_logger = GPSEventLogger()

        # State tracking for event detection
        self._had_fix = False
        self._last_data_time = None
        self._in_timeout = False

    def run(self):
        self.running = True

        # Emit a status so the UI knows it's actively scanning
        if self.driver.port == "AUTO":
            self.connection_status.emit(True, "Scanning COM ports...")

        # Connect Hardware (This triggers auto-discovery if port is AUTO)
        if not self.driver.connect():
            self.connection_status.emit(False, "Failed to find/connect to GPS")
            self.event_logger.log(
                GPSEventLogger.CONNECTION_FAILED,
                f"Auto-discovery failed. No GPS found on any COM port."
            )
            self.running = False
            return

        # Update UI with the exact port that was discovered
        self.connection_status.emit(True, f"Connected ({self.driver.port})")
        self.event_logger.log(
            GPSEventLogger.CONNECTION_OK,
            f"Connected on {self.driver.port} at {self.driver.baudrate} baud"
        )

        self._last_data_time = time.time()
        
        # We start with no fix. We log it so it's clear the GPS is connected but searching.
        self.event_logger.log(
            GPSEventLogger.FIX_LOST,
            "GPS connected but waiting for satellite fix..."
        )

        # Polling Loop
        while self.running:
            try:
                # Drain the serial buffer completely every cycle
                # GPS modules send bursts of 5-15 sentences at once.
                while self.running:
                    new_data = self.driver.read_and_parse()
                    if not new_data:
                        break
                    
                    self._last_data_time = time.time()
                    self.gps_data_updated.emit(new_data)

                    # Check for data timeout recovery
                    if self._in_timeout:
                        self._in_timeout = False
                        self.event_logger.log(
                            GPSEventLogger.DATA_RESUMED,
                            "Valid NMEA data received after timeout period"
                        )

                    # Check for fix transitions
                    fix_quality = new_data.get("fix_quality", 0)
                    has_fix = fix_quality > 0

                    if has_fix and not self._had_fix:
                        self.event_logger.log(
                            GPSEventLogger.FIX_ACQUIRED,
                            f"GPS fix acquired (quality={fix_quality}, "
                            f"sats={new_data.get('satellites_in_view', 0)})"
                        )
                    elif not has_fix and self._had_fix:
                        self.event_logger.log(
                            GPSEventLogger.FIX_LOST,
                            f"GPS fix lost. Last known position: "
                            f"lat={new_data.get('latitude', 0):.6f}, "
                            f"lon={new_data.get('longitude', 0):.6f}"
                        )

                    self._had_fix = has_fix

                else:
                    # No data this cycle — check for timeout
                    elapsed = time.time() - self._last_data_time
                    if elapsed > DATA_TIMEOUT_SECONDS and not self._in_timeout:
                        self._in_timeout = True
                        self.event_logger.log(
                            GPSEventLogger.DATA_TIMEOUT,
                            f"No valid NMEA data for {elapsed:.1f}s. "
                            f"Possible cable disconnect or signal obstruction."
                        )

            except serial.SerialException as e:
                self.event_logger.log(
                    GPSEventLogger.SERIAL_ERROR,
                    f"Serial port error: {e}"
                )
                self.connection_status.emit(False, "Serial error — GPS disconnected")
                self.running = False
                break

            except Exception as e:
                self.event_logger.log(
                    GPSEventLogger.SERIAL_ERROR,
                    f"Unexpected error during GPS read: {e}"
                )
                logger.error(f"GPS Worker Exception: {e}")

            # Prevent 100% CPU lockup; 10ms is fine for 115200bps processing
            time.sleep(0.01)

    def stop(self):
        self.running = False
        self.wait()
        self.driver.disconnect()
        self.event_logger.log(
            GPSEventLogger.WORKER_STOPPED,
            "GPS worker stopped (application shutdown or manual stop)"
        )
        self.event_logger.close()