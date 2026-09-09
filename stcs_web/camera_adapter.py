"""
Thread-safe adapter around the existing STCS V1 ScienceCameraDriver.

WHY: The existing camera driver (Princeton Instruments PIXIS 512B via
LightField COM/.NET) uses blocking calls and was designed for a QThread
worker. FastAPI cannot block its async event loop. This adapter runs all
camera operations on a dedicated daemon thread with a command queue,
mirroring the pattern of the existing CameraWorker but without PyQt6.

The adapter imports and wraps ScienceCameraDriver directly. It does NOT
reimplement any camera logic. All camera configuration, acquisition, and
hardware interaction is delegated to the existing tested driver.

Architecture:
  FastAPI async handler
      ↓ asyncio.to_thread(adapter.method)
  CameraAdapter (main thread, thread-safe state)
      ↓ queue + dedicated thread
  ScienceCameraDriver (existing, untouched)
      ↓ COM/.NET
  LightField → PIXIS 512B CCD
"""

import hashlib
import logging
import os
import queue
import sys
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("CameraAdapter")


class CameraState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    READY = "READY"
    CONFIGURING = "CONFIGURING"
    EXPOSING = "EXPOSING"
    READING = "READING"
    SAVING = "SAVING"
    COMPLETE = "COMPLETE"
    ABORTING = "ABORTING"
    ERROR = "ERROR"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    SIMULATION = "SIMULATION"


class CameraAdapter:
    """Thread-safe wrapper around ScienceCameraDriver.

    All public methods are safe to call from FastAPI async handlers via
    asyncio.to_thread(). They block the calling thread (not the event loop)
    while waiting for the camera worker thread to complete.
    """

    def __init__(self):
        self._driver = None
        self._state = CameraState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._command_queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

        # Cached status values (updated by worker thread)
        self._connected = False
        self._mock_mode = False
        self._temperature: Optional[float] = None
        self._last_file: Optional[str] = None
        self._last_error: Optional[str] = None
        self._connect_time: Optional[float] = None
        self._last_acquire_time: Optional[float] = None
        self._status_lock = threading.Lock()

        # Event for synchronous command completion
        self._result_event = threading.Event()
        self._result_value: Any = None
        self._result_error: Optional[str] = None

        self._init_driver()

    def _init_driver(self):
        """Import and instantiate the existing ScienceCameraDriver.

        The driver handles its own architecture checks, DLL loading, and
        mock mode fallback. We do NOT modify its behavior.
        """
        try:
            # Add stcs_v1 to path so we can import the driver
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            stcs_v1_src = os.path.join(project_root, "stcs_v1", "src")
            if stcs_v1_src not in sys.path:
                sys.path.insert(0, stcs_v1_src)

            from drivers.camera.science_driver import ScienceCameraDriver
            self._driver = ScienceCameraDriver()

            if self._driver.mock_mode:
                with self._state_lock:
                    self._state = CameraState.SIMULATION
                self._mock_mode = True
                logger.info("Camera adapter initialized in SIMULATION mode (mock driver)")
            else:
                logger.info("Camera adapter initialized (real driver)")
        except Exception as e:
            logger.warning(f"Camera driver unavailable: {e}")
            with self._state_lock:
                self._state = CameraState.NOT_AVAILABLE
            self._driver = None

    def _start_worker(self):
        """Start the camera worker thread if not running."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="CameraWorker"
        )
        self._worker_thread.start()

    def _worker_loop(self):
        """Worker thread: processes commands from the queue."""
        while self._running:
            try:
                task = self._command_queue.get(timeout=0.2)
                cmd_name, cmd_func, cmd_args, cmd_kwargs = task
                try:
                    result = cmd_func(*cmd_args, **cmd_kwargs)
                    self._result_value = result
                    self._result_error = None
                except Exception as e:
                    self._result_value = None
                    self._result_error = str(e)
                    logger.error(f"Camera command '{cmd_name}' failed: {e}")
                finally:
                    self._result_event.set()
                    self._command_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                self._result_value = None
                self._result_error = str(e)
                self._result_event.set()

    def _execute(self, name: str, func: Callable, *args, **kwargs) -> Any:
        """Submit a command to the worker thread and wait for completion."""
        self._start_worker()
        self._result_event.clear()
        self._result_value = None
        self._result_error = None
        self._command_queue.put((name, func, args, kwargs))
        # Wait up to 180s for camera operations (acquire can take 120s + margins)
        if not self._result_event.wait(timeout=180):
            raise TimeoutError(f"Camera command '{name}' timed out after 180s")
        if self._result_error:
            raise RuntimeError(self._result_error)
        return self._result_value

    # ── Public API ─────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current camera status. Thread-safe, non-blocking."""
        with self._state_lock:
            state = self._state.value
        with self._status_lock:
            return {
                "state": state,
                "connected": self._connected,
                "mock_mode": self._mock_mode,
                "temperature": self._temperature,
                "last_file": self._last_file,
                "last_error": self._last_error,
                "connect_time": self._connect_time,
                "last_acquire_time": self._last_acquire_time,
                "driver_available": self._driver is not None,
            }

    def connect(self) -> bool:
        """Connect to the camera via LightField. Blocks until complete."""
        if self._driver is None:
            with self._state_lock:
                self._state = CameraState.NOT_AVAILABLE
            raise RuntimeError("Camera driver not available")

        with self._state_lock:
            if self._state in (CameraState.CONNECTED, CameraState.READY):
                return True
            self._state = CameraState.CONNECTING

        try:
            success = self._execute("connect", self._driver.connect)
            with self._state_lock:
                self._state = CameraState.CONNECTED if success else CameraState.DISCONNECTED
            with self._status_lock:
                self._connected = success
                self._mock_mode = getattr(self._driver, "mock_mode", False)
                if success:
                    self._connect_time = time.time()
                    # Read initial temperature
                    try:
                        self._temperature = self._driver.get_current_temperature()
                    except Exception:
                        self._temperature = None
            return success
        except Exception as e:
            with self._state_lock:
                self._state = CameraState.ERROR
            with self._status_lock:
                self._last_error = str(e)
            raise

    def disconnect(self):
        """Disconnect from the camera."""
        if self._driver is None:
            return
        try:
            self._execute("dispose", self._driver.dispose)
        except Exception:
            pass
        with self._state_lock:
            self._state = CameraState.DISCONNECTED
        with self._status_lock:
            self._connected = False
            self._temperature = None

    def is_connected(self) -> bool:
        """Check if the camera is connected. Uses driver heartbeat."""
        if self._driver is None:
            return False
        try:
            return self._driver.is_connected()
        except Exception:
            return False

    def configure(self, settings: Dict[str, Any]) -> bool:
        """Apply camera configuration. settings keys match driver method names.

        Supported keys (mapped to existing driver methods):
          exposure: float (seconds) -> set_exposure
          gain: str ("low"/"medium"/"high") -> set_gain
          shutter: str ("normal"/"alwaysclosed"/"alwaysopen") -> set_shutter_mode
          adc_speed: str ("2 MHz"/"100 kHz") -> set_adc_speed
          temperature: float -> set_temperature
          readout_mode: str ("full frame"/"kinetics") -> set_readout_mode
          frames_to_save: int -> set_frames_to_save
          roi_selection: str -> set_roi_selection
          binning: [x, y] -> set_binned_params
          binning_provider: str -> set_binning_provider
          base_filename: str -> set_base_filename
          save_directory: str -> set_save_directory
          attach_date: bool -> set_attach_date
          attach_time: bool -> set_attach_time
          attach_increment: bool -> set_attach_increment
          increment_number: int -> set_increment_number
          increment_digits: int -> set_increment_digits
          date_format: str -> set_date_format
          time_format: str -> set_time_format
          time_stamping: int -> set_time_stamping
          frame_tracking: bool -> set_frame_tracking
          trigger_response: str -> set_trigger_response
          trigger_determination: str -> set_trigger_determination
          output_signal: str -> set_output_signal
        """
        if self._driver is None:
            raise RuntimeError("Camera driver not available")
        if not self.is_connected():
            raise RuntimeError("Camera not connected")

        with self._state_lock:
            self._state = CameraState.CONFIGURING

        method_map = {
            "exposure": ("set_exposure", [float]),
            "gain": ("set_gain", [str]),
            "shutter": ("set_shutter_mode", [str]),
            "adc_speed": ("set_adc_speed", [str]),
            "temperature": ("set_temperature", [float]),
            "readout_mode": ("set_readout_mode", [str]),
            "frames_to_save": ("set_frames_to_save", [int]),
            "roi_selection": ("set_roi_selection", [str]),
            "binning_provider": ("set_binning_provider", [str]),
            "base_filename": ("set_base_filename", [str]),
            "save_directory": ("set_save_directory", [str]),
            "attach_date": ("set_attach_date", [bool]),
            "attach_time": ("set_attach_time", [bool]),
            "attach_increment": ("set_attach_increment", [bool]),
            "increment_number": ("set_increment_number", [int]),
            "increment_digits": ("set_increment_digits", [int]),
            "date_format": ("set_date_format", [str]),
            "time_format": ("set_time_format", [str]),
            "time_stamping": ("set_time_stamping", [int]),
            "frame_tracking": ("set_frame_tracking", [bool]),
            "trigger_response": ("set_trigger_response", [str]),
            "trigger_determination": ("set_trigger_determination", [str]),
            "output_signal": ("set_output_signal", [str]),
        }

        applied = []
        for key, value in settings.items():
            if key == "binning" and isinstance(value, (list, tuple)) and len(value) == 2:
                # Special handling for binning pair
                try:
                    self._driver.set_binned_params(int(value[0]), int(value[1]))
                    applied.append("binning")
                except Exception as e:
                    logger.warning(f"Failed to set binning: {e}")
                continue
            if key in method_map:
                method_name, _ = method_map[key]
                method = getattr(self._driver, method_name, None)
                if method:
                    try:
                        method(value)
                        applied.append(key)
                    except Exception as e:
                        logger.warning(f"Failed to set {key}: {e}")

        with self._state_lock:
            self._state = CameraState.READY

        return len(applied) > 0

    def acquire_image(self, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Acquire an image. Blocks until complete (up to ~120s).

        Args:
            settings: Optional camera settings to apply before acquisition.
                      Same format as configure().

        Returns:
            dict with keys: file_path, filename, file_size, checksum, success, error
        """
        if self._driver is None:
            raise RuntimeError("Camera driver not available")
        if not self.is_connected():
            raise RuntimeError("Camera not connected")

        with self._state_lock:
            self._state = CameraState.EXPOSING

        start_time = time.time()
        try:
            # Apply settings if provided
            if settings:
                self.configure(settings)

            # Set exposure if provided in settings (driver expects seconds)
            if settings and "exposure" in settings:
                # Already applied via configure, but ensure it's set
                pass

            # Trigger acquisition — this blocks in the worker thread
            with self._state_lock:
                self._state = CameraState.EXPOSING

            image_path = self._driver.acquire_image()

            with self._state_lock:
                self._state = CameraState.SAVING

            elapsed = time.time() - start_time

            if image_path and os.path.exists(image_path):
                file_size = os.path.getsize(image_path)
                checksum = self._compute_checksum(image_path)
                filename = os.path.basename(image_path)

                with self._status_lock:
                    self._last_file = image_path
                    self._last_acquire_time = time.time()

                with self._state_lock:
                    self._state = CameraState.COMPLETE

                return {
                    "success": True,
                    "file_path": image_path,
                    "filename": filename,
                    "file_size": file_size,
                    "checksum": checksum,
                    "elapsed_s": elapsed,
                    "error": None,
                }
            else:
                with self._state_lock:
                    self._state = CameraState.ERROR
                with self._status_lock:
                    self._last_error = "Acquisition completed but no image file found"
                return {
                    "success": False,
                    "file_path": None,
                    "filename": None,
                    "file_size": None,
                    "checksum": None,
                    "elapsed_s": elapsed,
                    "error": "No image file produced",
                }

        except Exception as e:
            elapsed = time.time() - start_time
            with self._state_lock:
                self._state = CameraState.ERROR
            with self._status_lock:
                self._last_error = str(e)
            return {
                "success": False,
                "file_path": None,
                "filename": None,
                "file_size": None,
                "checksum": None,
                "elapsed_s": elapsed,
                "error": str(e),
            }

    def get_temperature(self) -> Optional[float]:
        """Read current sensor temperature."""
        if self._driver is None or not self.is_connected():
            return None
        try:
            temp = self._driver.get_current_temperature()
            with self._status_lock:
                self._temperature = temp
            return temp
        except Exception:
            return None

    def set_temperature(self, temp: float):
        """Set sensor temperature setpoint."""
        if self._driver is None or not self.is_connected():
            raise RuntimeError("Camera not connected")
        self._driver.set_temperature(temp)

    def get_readout_status(self) -> Dict[str, Any]:
        """Get readout timing info."""
        if self._driver is None or not self.is_connected():
            return {"time_ms": 0, "fps": 0, "frames_per": 0}
        try:
            return self._driver.get_readout_status()
        except Exception:
            return {"time_ms": 0, "fps": 0, "frames_per": 0}

    def get_example_filename(self) -> str:
        """Get LightField's preview filename."""
        if self._driver is None or not self.is_connected():
            return ""
        try:
            return self._driver.get_example_filename()
        except Exception:
            return ""

    def reset_state(self):
        """Reset to READY state after an acquisition completes or fails."""
        with self._state_lock:
            if self._state in (CameraState.COMPLETE, CameraState.ERROR):
                if self._connected:
                    self._state = CameraState.READY
                else:
                    self._state = CameraState.DISCONNECTED

    def dispose(self):
        """Clean up the driver and stop the worker thread."""
        self._running = False
        if self._driver:
            try:
                self._driver.dispose()
            except Exception:
                pass
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)
        with self._state_lock:
            self._state = CameraState.DISCONNECTED

    # ── Internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _compute_checksum(file_path: str) -> str:
        """Compute SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception:
            return ""


# ── Module singleton ───────────────────────────────────────────────────────
_adapter: Optional[CameraAdapter] = None
_adapter_lock = threading.Lock()


def get_camera_adapter() -> Optional[CameraAdapter]:
    """Get or create the singleton camera adapter."""
    global _adapter
    if _adapter is None:
        with _adapter_lock:
            if _adapter is None:
                _adapter = CameraAdapter()
    return _adapter


def dispose_camera_adapter():
    """Dispose the singleton camera adapter."""
    global _adapter
    if _adapter is not None:
        _adapter.dispose()
        _adapter = None
