"""
Camera observation service — acquisition lifecycle, telescope state capture,
concurrency control, and database integration.

WHY: The camera hardware is controlled by the existing ScienceCameraDriver
via the CameraAdapter. This service adds the scientific observation layer:
- Acquisition lock (one acquisition at a time)
- Telescope state capture at exposure start
- Observation record creation/update in PostgreSQL
- File metadata recording
- Privacy enforcement

The service never modifies camera behavior. It wraps the adapter with
observation lifecycle management.

Architecture:
  FastAPI handler
      ↓
  CameraService (this module)
      ↓
  CameraAdapter → ScienceCameraDriver → LightField → CCD
      ↓
  obs_store (PostgreSQL)
"""

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional

from .camera_adapter import CameraAdapter, CameraState, get_camera_adapter
from . import obs_store

logger = logging.getLogger("CameraService")


class AcquisitionLock:
    """Server-side lock ensuring only one acquisition runs at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._acquiring = False
        self._owner: Optional[str] = None
        self._started_at: Optional[float] = None

    def acquire(self, username: str) -> bool:
        """Try to acquire the lock. Returns True if acquired."""
        got = self._lock.acquire(blocking=False)
        if got:
            self._acquiring = True
            self._owner = username
            self._started_at = time.time()
            return True
        return False

    def release(self):
        """Release the lock."""
        self._acquiring = False
        self._owner = None
        self._started_at = None
        try:
            self._lock.release()
        except Exception:
            pass

    @property
    def is_locked(self) -> bool:
        return self._acquiring

    @property
    def owner(self) -> Optional[str]:
        return self._owner

    @property
    def elapsed(self) -> Optional[float]:
        if self._started_at:
            return time.time() - self._started_at
        return None


class CameraService:
    """High-level camera observation service.

    Manages the full acquisition lifecycle:
    1. Validate request (auth, camera connected, not busy)
    2. Acquire acquisition lock
    3. Capture telescope state snapshot
    4. Create observation record in DB (status: acquiring)
    5. Apply camera settings
    6. Trigger acquisition via adapter
    7. On success: record file, update observation (status: completed)
    8. On failure: update observation (status: failed)
    9. Release acquisition lock
    """

    def __init__(self, adapter: Optional[CameraAdapter] = None,
                 observatory_snapshot_fn=None):
        self._adapter = adapter or get_camera_adapter()
        self._acq_lock = AcquisitionLock()
        self._snapshot_fn = observatory_snapshot_fn
        self._current_obs_id: Optional[int] = None
        self._current_username: Optional[str] = None
        self._last_acquisition: Optional[Dict[str, Any]] = None

    def _get_telemetry_snapshot(self) -> Optional[Dict[str, Any]]:
        """Capture current telescope state from the telemetry layer."""
        if self._snapshot_fn:
            try:
                return self._snapshot_fn()
            except Exception as e:
                logger.warning(f"Failed to capture telescope snapshot: {e}")
        # Fallback: try importing observatory module
        try:
            from . import observatory
            return observatory.observatory_snapshot()
        except Exception:
            return None

    def _extract_telescope_state(self, snap: Optional[Dict]) -> Optional[Dict]:
        """Extract the relevant telescope state fields for observation metadata."""
        if snap is None:
            return None
        state = {}
        # Coordinates
        for key in ("ra_hours", "dec_deg", "ha_hours", "lst_hours",
                     "alt_deg", "az_deg"):
            val = snap.get(key)
            if val is not None:
                state[key] = val
        # Tracking/dome
        for key in ("tracking", "slewing", "dome_state", "dome_az_deg"):
            val = snap.get(key)
            if val is not None:
                state[key] = val
        # Safety
        for key in ("safety_limit_active", "safety_limit_message"):
            val = snap.get(key)
            if val is not None:
                state[key] = val
        # Weather
        weather = snap.get("weather")
        if weather and isinstance(weather, dict):
            wv = weather.get("values")
            if wv:
                state["weather"] = wv
        # Environment breakdown (safety states, freshness, source)
        env = snap.get("environment")
        if env and isinstance(env, dict):
            state["environment"] = {
                "weather_status": env.get("weather_status"),
                "weather_source": env.get("weather_source"),
                "weather_age_fmt": env.get("weather_age_fmt"),
                "weather_age_s": env.get("weather_age_s"),
                "humidity_state": env.get("humidity_state"),
                "wind_state": env.get("wind_state"),
                "rain_state": env.get("rain_state"),
                "altitude_state": env.get("altitude_state"),
                "temperature": env.get("temperature"),
                "humidity": env.get("humidity"),
                "dew_point": env.get("dew_point"),
            }
        # Mode
        mode = snap.get("mode")
        if mode:
            state["mode"] = mode
        # Telemetry source
        source = snap.get("telemetry_source")
        if source:
            state["telemetry_source"] = source
        return state if state else None

    def get_camera_status(self) -> Dict[str, Any]:
        """Return comprehensive camera status for the UI."""
        if self._adapter is None:
            return {
                "available": False,
                "state": "NOT_AVAILABLE",
                "connected": False,
                "mock_mode": False,
                "temperature": None,
                "exposing": False,
                "acquisition_lock": {
                    "locked": self._acq_lock.is_locked,
                    "owner": self._acq_lock.owner,
                    "elapsed_s": self._acq_lock.elapsed,
                },
                "current_obs_id": self._current_obs_id,
                "last_acquisition": self._last_acquisition,
                "error": "Camera driver not available",
            }
        adapter_status = self._adapter.get_status()
        return {
            "available": True,
            "state": adapter_status["state"],
            "connected": adapter_status["connected"],
            "mock_mode": adapter_status["mock_mode"],
            "temperature": adapter_status["temperature"],
            "exposing": adapter_status["state"] in (
                CameraState.EXPOSING.value,
                CameraState.READING.value,
                CameraState.CONFIGURING.value,
            ),
            "last_file": adapter_status["last_file"],
            "last_error": adapter_status["last_error"],
            "acquisition_lock": {
                "locked": self._acq_lock.is_locked,
                "owner": self._acq_lock.owner,
                "elapsed_s": self._acq_lock.elapsed,
            },
            "current_obs_id": self._current_obs_id,
            "last_acquisition": self._last_acquisition,
            "driver_available": adapter_status["driver_available"],
        }

    def connect_camera(self) -> Dict[str, Any]:
        """Connect to the camera."""
        if self._adapter is None:
            return {"success": False, "error": "Camera driver not available"}
        try:
            success = self._adapter.connect()
            if success:
                obs_store.record_audit(
                    "system", "camera_connected",
                    f"mock={self._adapter._mock_mode}"
                )
            return {"success": success, "mock_mode": self._adapter._mock_mode}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def disconnect_camera(self) -> Dict[str, Any]:
        """Disconnect from the camera."""
        if self._adapter is None:
            return {"success": False, "error": "Camera driver not available"}
        if self._acq_lock.is_locked:
            return {"success": False, "error": "Cannot disconnect during acquisition"}
        try:
            self._adapter.disconnect()
            obs_store.record_audit("system", "camera_disconnected")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def configure_camera(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Configure camera settings."""
        if self._adapter is None:
            return {"success": False, "error": "Camera driver not available"}
        if not self._adapter.is_connected():
            return {"success": False, "error": "Camera not connected"}
        try:
            self._adapter.configure(settings)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_acquisition(self, target: str, settings: Dict[str, Any],
                          username: str, notes: str = "") -> Dict[str, Any]:
        """Start a full observation acquisition cycle.

        This is the main entry point for scientific image acquisition.
        It performs the complete lifecycle:
        1. Validate
        2. Lock
        3. Capture telescope state
        4. Create observation record
        5. Acquire image
        6. Record file
        7. Complete observation
        8. Unlock
        """
        # 1. Validate
        if self._adapter is None:
            return {"success": False, "error": "Camera driver not available",
                    "status": "NOT_AVAILABLE"}
        if not self._adapter.is_connected():
            return {"success": False, "error": "Camera not connected",
                    "status": "DISCONNECTED"}
        if self._adapter.get_status()["state"] in (
            CameraState.EXPOSING.value, CameraState.READING.value
        ):
            return {"success": False, "error": "Camera busy",
                    "status": "BUSY"}

        # 2. Acquire lock
        if not self._acq_lock.acquire(username):
            return {"success": False,
                    "error": f"Acquisition already in progress by {self._acq_lock.owner}",
                    "status": "BUSY"}

        obs_id = None
        try:
            # 3. Capture telescope state
            snap = self._get_telemetry_snapshot()
            tel_state = self._extract_telescope_state(snap)

            # Extract RA/DEC for the observation record
            ra_deg = None
            dec_deg = None
            if tel_state:
                ra_h = tel_state.get("ra_hours")
                if ra_h is not None:
                    ra_deg = float(ra_h) * 15.0  # hours → degrees
                dec_deg = tel_state.get("dec_deg")

            # 4. Create observation record
            obs_id = obs_store.create_observation(
                owner_username=username,
                target=target,
                ra_deg=ra_deg,
                dec_deg=dec_deg,
                status="acquiring",
                notes=notes,
                telescope_state=tel_state,
                camera_settings=settings,
            )
            self._current_obs_id = obs_id
            self._current_username = username

            if obs_id is None:
                return {"success": False, "error": "Failed to create observation record",
                        "status": "ERROR"}

            obs_store.record_audit(username, "acquisition_requested",
                                   f"obs={obs_id} target={target}")

            # 5-6. Acquire image (blocking — runs in adapter's worker thread)
            result = self._adapter.acquire_image(settings)

            if result["success"]:
                # 7a. Record file in database
                file_id = obs_store.record_observation_file(
                    obs_id=obs_id,
                    filename=result["filename"],
                    file_path=result["file_path"],
                    kind="data",
                    checksum=result["checksum"],
                    file_size=result["file_size"],
                )

                # Update observation as completed
                obs_store.update_observation(
                    obs_id,
                    status="completed",
                    end_time=obs_store.utcnow(),
                    duration_s=result["elapsed_s"],
                )

                obs_store.record_audit(username, "acquisition_completed",
                                       f"obs={obs_id} file={result['filename']} "
                                       f"elapsed={result['elapsed_s']:.1f}s")

                self._last_acquisition = {
                    "obs_id": obs_id,
                    "file_id": file_id,
                    "filename": result["filename"],
                    "elapsed_s": result["elapsed_s"],
                    "success": True,
                }

                return {
                    "success": True,
                    "status": "COMPLETE",
                    "obs_id": obs_id,
                    "file_id": file_id,
                    "filename": result["filename"],
                    "file_size": result["file_size"],
                    "checksum": result["checksum"],
                    "elapsed_s": result["elapsed_s"],
                }
            else:
                # 7b. Acquisition failed
                obs_store.update_observation(
                    obs_id,
                    status="failed",
                    end_time=obs_store.utcnow(),
                    duration_s=result["elapsed_s"],
                    notes=f"Acquisition error: {result['error']}",
                )
                obs_store.record_audit(username, "acquisition_failed",
                                       f"obs={obs_id} error={result['error']}")
                self._last_acquisition = {
                    "obs_id": obs_id,
                    "filename": None,
                    "success": False,
                    "error": result["error"],
                }
                return {
                    "success": False,
                    "status": "ERROR",
                    "obs_id": obs_id,
                    "error": result["error"],
                }

        except Exception as e:
            logger.error(f"Acquisition lifecycle error: {e}")
            if obs_id:
                try:
                    obs_store.update_observation(
                        obs_id, status="failed",
                        notes=f"Service error: {e}",
                    )
                except Exception:
                    pass
            return {"success": False, "status": "ERROR", "error": str(e)}

        finally:
            # 8. Release lock and clean up
            self._acq_lock.release()
            self._current_obs_id = None
            self._current_username = None
            if self._adapter:
                self._adapter.reset_state()

    def get_acquisition_status(self) -> Dict[str, Any]:
        """Return current acquisition status (non-blocking)."""
        return {
            "locked": self._acq_lock.is_locked,
            "owner": self._acq_lock.owner,
            "elapsed_s": self._acq_lock.elapsed,
            "current_obs_id": self._current_obs_id,
            "camera_state": self._adapter.get_status()["state"] if self._adapter else "NOT_AVAILABLE",
            "last_acquisition": self._last_acquisition,
        }

    def abort_acquisition(self, username: str) -> Dict[str, Any]:
        """Abort the current acquisition.

        NOTE: The existing ScienceCameraDriver does NOT have an explicit abort
        method. The LightField acquisition loop polls IsRunning. An abort would
        require LightField's own abort mechanism which is not exposed in the
        current driver. This method logs the abort request and releases the lock.
        """
        if not self._acq_lock.is_locked:
            return {"success": False, "error": "No acquisition in progress"}
        if self._acq_lock.owner != username:
            return {"success": False, "error": "Only the acquisition owner can abort"}

        obs_id = self._current_obs_id
        if obs_id:
            obs_store.update_observation(
                obs_id, status="aborted",
                notes=f"Aborted by {username}",
            )
            obs_store.record_audit(username, "acquisition_aborted",
                                   f"obs={obs_id}")

        self._acq_lock.release()
        self._current_obs_id = None
        self._current_username = None
        if self._adapter:
            self._adapter.reset_state()

        return {"success": True, "status": "ABORTED"}


# ── Module singleton ───────────────────────────────────────────────────────
_service: Optional[CameraService] = None
_service_lock = threading.Lock()


def get_camera_service() -> Optional[CameraService]:
    """Get or create the singleton camera service."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                adapter = get_camera_adapter()
                _service = CameraService(adapter=adapter)
    return _service


def start_camera_service():
    """Initialize the camera service and adapter."""
    global _service
    with _service_lock:
        if _service is None:
            adapter = get_camera_adapter()
            _service = CameraService(adapter=adapter)
            logger.info("Camera service started")
    return _service


def stop_camera_service():
    """Dispose the camera service and adapter."""
    global _service
    if _service is not None:
        _service = None
    from .camera_adapter import dispose_camera_adapter
    dispose_camera_adapter()
    logger.info("Camera service stopped")
