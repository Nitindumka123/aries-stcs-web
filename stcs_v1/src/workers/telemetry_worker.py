import time
import logging
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from src.drivers.mount.mount_coordinator import MountCoordinator

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TelemetryWorker")

class TelemetryWorker(QThread):
    """
    Background thread that polls the telescope hardware via Serial (Path B).
    Uses MountCoordinator to talk to Arduino R4s.
    """
    # Signals
    telemetry_updated = pyqtSignal(dict)  # Carries the RA/DEC/Dome data dict
    connection_status = pyqtSignal(bool, str) # Success/Fail, Message
    log_message = pyqtSignal(str, str) # Level, Message

    def __init__(self):
        super().__init__()
        self.coordinator = MountCoordinator()
        self.running = False
        self.polling_interval = 0.1 # 100ms = 10Hz (Fast enough for smooth UI)
        self.mutex = QMutex() # Protect access to coordinator during Sync vs Polling
        self.motion_state = None  # Injected by MainWindow after construction

    def run(self):
        """
        The main loop. This runs in a separate thread.
        """
        self.running = True
        
        # 1. Attempt Connection
        try:
            self.log_message.emit("INFO", "Telemetry Worker starting hardware connection...")
            
            # Lock while connecting to ensure thread safety
            with QMutexLocker(self.mutex):
                self.coordinator.connect_hardware()
            
            self.connection_status.emit(True, "Connected")
            self.log_message.emit("INFO", "All Systems Online (Serial Mode).")
        except Exception as e:
            self.connection_status.emit(False, str(e))
            self.log_message.emit("ERROR", f"Connection Failed: {e}")
            self.running = False
            return

        # 2. Polling Loop
        while self.running:
            try:
                # Feed slewing state from MotionState into MountCoordinator
                # so Z-pulse homing detection is suppressed during active slews.
                if self.motion_state is not None:
                    self.coordinator.is_slewing = self.motion_state.is_slewing

                # Fetch data from hardware (Thread-blocking I/O happens here)
                # Lock while reading to avoid conflict with Sync commands running on other threads
                with QMutexLocker(self.mutex):
                    data = self.coordinator.get_telemetry()
                
                # Send data to GUI
                self.telemetry_updated.emit(data)
                
            except Exception as e:
                self.log_message.emit("ERROR", f"Polling Error: {e}")
                # Optional: specific handling for disconnection
                # For now, we log and retry next loop
            
            # Sleep to prevent 100% CPU usage
            time.sleep(self.polling_interval)

    def request_sync(self, target_dec_deg, target_dome_az):
        """
        Thread-safe method to request a coordinate sync.
        The UI calls this (from UI Thread), but it locks the mutex to safely
        access the coordinator shared with the background thread.
        """
        self.log_message.emit("INFO", f"Sync Requested: DEC={target_dec_deg}, DOME={target_dome_az}")
        
        # Protect the shared coordinator resource
        with QMutexLocker(self.mutex):
            try:
                self.coordinator.sync_coordinates(target_dec_deg, target_dome_az)
                self.log_message.emit("INFO", "Sync Command Executed Successfully.")
            except Exception as e:
                self.log_message.emit("ERROR", f"Sync Failed: {e}")

    def request_set_dec_home(self, home_dec_deg):
        """
        Thread-safe method to set the DEC manual home.
        Called from UI Thread; locks the mutex to safely access
        the shared coordinator on the background thread.
        """
        self.log_message.emit("INFO", f"DEC Home Requested: {home_dec_deg:.4f}°")

        with QMutexLocker(self.mutex):
            try:
                self.coordinator.set_dec_home(home_dec_deg)
                self.log_message.emit("INFO", f"DEC Home Set Successfully to {home_dec_deg:.4f}°")
            except Exception as e:
                self.log_message.emit("ERROR", f"DEC Home Failed: {e}")
                raise  # Re-raise so caller can show error dialog

    def stop(self):
        """Safe stop method."""
        self.running = False
        self.wait() # Wait for thread to finish current loop
        
        # Lock while disconnecting to avoid race conditions
        with QMutexLocker(self.mutex):
            self.coordinator.disconnect_hardware()
