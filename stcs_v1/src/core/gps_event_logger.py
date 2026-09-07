# src/core/gps_event_logger.py
import csv
import os
import threading
import logging
from datetime import datetime

logger = logging.getLogger("GPSEventLogger")


class GPSEventLogger:
    """
    Thread-safe CSV logger for GPS events (failures, data gaps, anomalies).
    Creates daily log files in data/gps_events/.
    """

    # Event constants
    CONNECTION_OK = "CONNECTION_OK"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    FIX_ACQUIRED = "FIX_ACQUIRED"
    FIX_LOST = "FIX_LOST"
    DATA_TIMEOUT = "DATA_TIMEOUT"
    DATA_RESUMED = "DATA_RESUMED"
    SERIAL_ERROR = "SERIAL_ERROR"
    WORKER_STOPPED = "WORKER_STOPPED"
    DISCONNECTED = "DISCONNECTED"

    LEVELS = {
        CONNECTION_OK: "INFO",
        CONNECTION_FAILED: "ERROR",
        FIX_ACQUIRED: "INFO",
        FIX_LOST: "WARNING",
        DATA_TIMEOUT: "WARNING",
        DATA_RESUMED: "INFO",
        SERIAL_ERROR: "ERROR",
        WORKER_STOPPED: "INFO",
        DISCONNECTED: "WARNING",
    }

    CSV_HEADER = ["timestamp", "level", "event", "message"]

    def __init__(self):
        self._lock = threading.Lock()
        self._base_dir = self._resolve_data_dir()
        self._current_date = None
        self._file = None
        self._writer = None

    def _resolve_data_dir(self):
        """Resolves data/gps_events/ relative to the project root."""
        # Navigate from src/core/ up to project root
        external_root = os.environ.get('STCS_EXTERNAL_ROOT', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        return os.path.join(external_root, "data", "gps_events")

    def _ensure_file(self):
        """Opens or rotates the CSV file for the current date."""
        today = datetime.now().strftime("%Y-%m-%d")

        if self._current_date == today and self._file and not self._file.closed:
            return  # Already writing to today's file

        # Close previous file if open
        self._close_file()

        # Create directory if needed
        os.makedirs(self._base_dir, exist_ok=True)

        filepath = os.path.join(self._base_dir, f"gps_events_{today}.csv")
        file_exists = os.path.exists(filepath)

        self._file = open(filepath, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._current_date = today

        # Write header only for new files
        if not file_exists or os.path.getsize(filepath) == 0:
            self._writer.writerow(self.CSV_HEADER)
            self._file.flush()

        logger.debug(f"GPS event log file: {filepath}")

    def _close_file(self):
        """Safely closes the current CSV file."""
        if self._file and not self._file.closed:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._writer = None
        self._current_date = None

    def log(self, event, message=""):
        """
        Logs a GPS event to the daily CSV file.

        Args:
            event: One of the event constants (e.g., CONNECTION_FAILED)
            message: Human-readable description of what happened
        """
        level = self.LEVELS.get(event, "INFO")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        with self._lock:
            try:
                self._ensure_file()
                self._writer.writerow([timestamp, level, event, message])
                self._file.flush()  # Flush immediately for crash safety
            except Exception as e:
                logger.error(f"Failed to write GPS event log: {e}")

        # Also mirror to Python's standard logger
        log_msg = f"[GPS] {event}: {message}"
        if level == "ERROR":
            logger.error(log_msg)
        elif level == "WARNING":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def close(self):
        """Closes the log file. Call on application shutdown."""
        with self._lock:
            self._close_file()
