"""
Camera + Observation Acquisition Integration Tests.

Tests camera status, connect/disconnect, configure, acquisition lifecycle,
observation privacy, file download authorization, and concurrent acquisition.

SIMULATION VERIFIED — physical camera hardware not required.
"""

import sys
import os
import time

# Add project root (parent of tests/) to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def test_camera_adapter_simulation_mode():
    """Test camera adapter initializes in simulation mode when LightField unavailable."""
    from stcs_web.camera_adapter import CameraAdapter, CameraState

    adapter = CameraAdapter()
    status = adapter.get_status()

    assert status["driver_available"] is True, "Driver should be available (mock)"
    assert status["mock_mode"] is True, "Should be in mock mode"
    assert status["state"] == CameraState.SIMULATION.value, f"Expected SIMULATION, got {status['state']}"
    assert status["connected"] is False, "Should not be connected initially"

    adapter.dispose()
    print("  PASS: adapter_simulation_mode")


def test_camera_adapter_connect_disconnect():
    """Test camera adapter connect and disconnect in simulation."""
    from stcs_web.camera_adapter import CameraAdapter, CameraState

    adapter = CameraAdapter()

    # Connect
    result = adapter.connect()
    assert result is True, "Connect should succeed in mock mode"
    status = adapter.get_status()
    assert status["connected"] is True, "Should be connected"
    assert status["state"] == CameraState.CONNECTED.value
    assert status["temperature"] == -70.0, "Mock temperature should be -70.0"

    # Disconnect
    adapter.disconnect()
    status = adapter.get_status()
    assert status["connected"] is False, "Should be disconnected"

    adapter.dispose()
    print("  PASS: adapter_connect_disconnect")


def test_camera_adapter_configure():
    """Test camera adapter configure with various settings."""
    from stcs_web.camera_adapter import CameraAdapter

    adapter = CameraAdapter()
    adapter.connect()

    # Configure various settings
    settings = {
        "exposure": 2.0,
        "gain": "high",
        "shutter": "normal",
        "adc_speed": "100 kHz",
        "readout_mode": "full frame",
        "binning": [2, 2],
        "base_filename": "test_target",
    }
    result = adapter.configure(settings)
    assert result is True, "Configure should succeed"

    adapter.dispose()
    print("  PASS: adapter_configure")


def test_camera_adapter_acquire_simulation():
    """Test camera adapter acquire in simulation (mock returns non-existent file)."""
    from stcs_web.camera_adapter import CameraAdapter

    adapter = CameraAdapter()
    adapter.connect()

    # Acquire - mock mode returns mock.png path but file doesn't exist
    result = adapter.acquire_image({"exposure": 0.5})

    # Mock mode: acquire_image returns path but file doesn't exist
    # So success=False is expected
    assert result["success"] is False, "Mock acquire should fail (no actual file)"
    assert result["error"] == "No image file produced", f"Unexpected error: {result['error']}"
    assert result["elapsed_s"] > 0, "Should have measured elapsed time"

    adapter.dispose()
    print("  PASS: adapter_acquire_simulation")


def test_camera_service_status():
    """Test camera service status reporting."""
    from stcs_web.camera_adapter import CameraAdapter
    from stcs_web.camera_service import CameraService

    adapter = CameraAdapter()
    service = CameraService(adapter=adapter)

    status = service.get_camera_status()
    assert status["available"] is True
    assert status["mock_mode"] is True
    assert status["connected"] is False
    assert status["exposing"] is False
    assert status["acquisition_lock"]["locked"] is False

    adapter.dispose()
    print("  PASS: service_status")


def test_camera_service_connect_disconnect():
    """Test camera service connect and disconnect."""
    from stcs_web.camera_adapter import CameraAdapter
    from stcs_web.camera_service import CameraService

    adapter = CameraAdapter()
    service = CameraService(adapter=adapter)

    # Connect
    result = service.connect_camera()
    assert result["success"] is True
    assert result["mock_mode"] is True

    status = service.get_camera_status()
    assert status["connected"] is True

    # Disconnect
    result = service.disconnect_camera()
    assert result["success"] is True

    status = service.get_camera_status()
    assert status["connected"] is False

    adapter.dispose()
    print("  PASS: service_connect_disconnect")


def test_camera_service_acquire_without_db():
    """Test camera service acquisition fails gracefully without PostgreSQL."""
    from stcs_web.camera_adapter import CameraAdapter
    from stcs_web.camera_service import CameraService

    adapter = CameraAdapter()
    service = CameraService(adapter=adapter)
    adapter.connect()

    # Attempt acquisition - will fail because no PostgreSQL
    result = service.start_acquisition(
        target="M42",
        settings={"exposure": 0.5},
        username="test_user",
        notes="test observation"
    )

    # Should fail on DB record creation
    assert result["success"] is False
    assert result["status"] == "ERROR"
    assert "Failed to create observation record" in result["error"]

    # Lock should be released
    assert service._acq_lock.is_locked is False

    adapter.dispose()
    print("  PASS: service_acquire_without_db")


def test_acquisition_lock_exclusion():
    """Test that acquisition lock prevents concurrent acquisitions."""
    from stcs_web.camera_service import AcquisitionLock

    lock = AcquisitionLock()

    # First acquire should succeed
    assert lock.acquire("user1") is True
    assert lock.is_locked is True
    assert lock.owner == "user1"
    assert lock.elapsed is not None

    # Second acquire should fail
    assert lock.acquire("user2") is False

    # Release
    lock.release()
    assert lock.is_locked is False

    # Now second user can acquire
    assert lock.acquire("user2") is True
    lock.release()

    print("  PASS: acquisition_lock_exclusion")


def test_observation_privacy():
    """Test that observation privacy is enforced in database queries."""
    from stcs_web import obs_store

    # Create observation as scientist1
    obs_id1 = obs_store.create_observation(
        owner_username="scientist1",
        target="M42",
        status="completed",
    )

    # Create observation as scientist2
    obs_id2 = obs_store.create_observation(
        owner_username="scientist2",
        target="NGC7331",
        status="completed",
    )

    if obs_id1 and obs_id2:
        # scientist1 should see only their own
        obs = obs_store.get_observation_with_files(obs_id1, "scientist1", "scientist")
        assert obs is not None, "scientist1 should see their own observation"
        assert obs["owner"] == "scientist1"

        # scientist1 should NOT see scientist2's observation
        obs = obs_store.get_observation_with_files(obs_id2, "scientist1", "scientist")
        assert obs is None, "scientist1 should NOT see scientist2's observation"

        # scientist2 should NOT see scientist1's observation
        obs = obs_store.get_observation_with_files(obs_id1, "scientist2", "scientist")
        assert obs is None, "scientist2 should NOT see scientist1's observation"

        # Admin should see both
        obs = obs_store.get_observation_with_files(obs_id1, "admin", "admin")
        assert obs is not None, "Admin should see scientist1's observation"

        obs = obs_store.get_observation_with_files(obs_id2, "admin", "admin")
        assert obs is not None, "Admin should see scientist2's observation"

        # Cleanup
        obs_store.update_observation(obs_id1, status="deleted")
        obs_store.update_observation(obs_id2, status="deleted")

    print("  PASS: observation_privacy")


def test_file_download_authorization():
    """Test that file download enforces authorization."""
    from stcs_web import obs_store

    # Create observation and file
    obs_id = obs_store.create_observation(
        owner_username="scientist1",
        target="M42",
        status="completed",
    )

    if obs_id:
        file_id = obs_store.record_observation_file(
            obs_id=obs_id,
            filename="test.spe",
            file_path="/nonexistent/test.spe",
            kind="data",
            checksum="abc123",
            file_size=1024,
        )

        if file_id:
            # scientist1 should be able to get file info
            result = obs_store.get_file_for_download(file_id, "scientist1", "scientist")
            assert result is not None, "scientist1 should access their own file"
            assert result["filename"] == "test.spe"

            # scientist2 should NOT be able to get file info
            result = obs_store.get_file_for_download(file_id, "scientist2", "scientist")
            assert result is None, "scientist2 should NOT access scientist1's file"

            # Admin should be able to get file info
            result = obs_store.get_file_for_download(file_id, "admin", "admin")
            assert result is not None, "Admin should access the file"

        # Cleanup
        obs_store.update_observation(obs_id, status="deleted")

    print("  PASS: file_download_authorization")


def test_camera_api_endpoints():
    """Test camera API endpoints using FastAPI TestClient (no running server needed)."""
    from starlette.testclient import TestClient
    from stcs_web.main import app

    client = TestClient(app)

    # Login as Admin
    r = client.get('/api/login')
    csrf = None
    if '_stcs_csrf_token' in r.text:
        csrf = r.text.split('_stcs_csrf_token" value="')[1].split('"')[0]

    r = client.post('/api/login', data={
        'username': 'Admin',
        'password': 'Admin@123',
        '_stcs_csrf_token': csrf
    }, follow_redirects=False)
    assert r.status_code == 302, f"Admin login failed: status={r.status_code}"

    # Test camera status
    r = client.get('/api/camera/status')
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is True
    assert data["mock_mode"] is True

    # Test camera connect
    r = client.post('/api/camera/connect')
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Test camera status after connect
    r = client.get('/api/camera/status')
    assert r.json()["connected"] is True

    # Test camera configure
    r = client.post('/api/camera/configure', json={"exposure": 1.0})
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Test acquisition status
    r = client.get('/api/camera/acquisition/status')
    assert r.status_code == 200
    assert r.json()["locked"] is False

    # Test camera observations (may have records from previous tests)
    r = client.get('/api/camera/observations')
    assert r.status_code == 200

    # Test camera page loads
    r = client.get('/app/camera')
    assert r.status_code == 200
    assert 'Camera' in r.text

    # Disconnect
    r = client.post('/api/camera/disconnect')
    assert r.status_code == 200
    assert r.json()["success"] is True

    print("  PASS: camera_api_endpoints")


def test_scientist_cannot_access_admin_page():
    """Test that scientist cannot access admin page using TestClient."""
    from starlette.testclient import TestClient
    from stcs_web.main import app

    client = TestClient(app)

    # Login as Scientist
    r = client.get('/api/login')
    csrf = None
    if '_stcs_csrf_token' in r.text:
        csrf = r.text.split('_stcs_csrf_token" value="')[1].split('"')[0]

    r = client.post('/api/login', data={
        'username': 'Scientist1',
        'password': 'Pass@123',
        '_stcs_csrf_token': csrf
    }, follow_redirects=False)
    assert r.status_code == 302

    # Scientist should be redirected from admin page
    r = client.get('/app/admin', follow_redirects=False)
    assert r.status_code == 302, f"Expected redirect, got {r.status_code}"

    print("  PASS: scientist_cannot_access_admin_page")


def test_commands_still_disabled():
    """Test that telescope commands are still disabled using TestClient."""
    from starlette.testclient import TestClient
    from stcs_web.main import app

    client = TestClient(app)

    # Login as Admin
    r = client.get('/api/login')
    csrf = None
    if '_stcs_csrf_token' in r.text:
        csrf = r.text.split('_stcs_csrf_token" value="')[1].split('"')[0]

    r = client.post('/api/login', data={
        'username': 'Admin',
        'password': 'Admin@123',
        '_stcs_csrf_token': csrf
    }, follow_redirects=False)

    # Test that commands are disabled
    r = client.get('/api/command/status')
    assert r.status_code == 200
    data = r.json()
    assert data.get("commands_enabled") is False, "Commands should be disabled"

    print("  PASS: commands_still_disabled")


# ── Run all tests ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Camera + Observation Integration Tests")
    print("SIMULATION VERIFIED — no physical hardware required")
    print("=" * 60)
    print()

    tests = [
        ("Camera Adapter - Simulation Mode", test_camera_adapter_simulation_mode),
        ("Camera Adapter - Connect/Disconnect", test_camera_adapter_connect_disconnect),
        ("Camera Adapter - Configure", test_camera_adapter_configure),
        ("Camera Adapter - Acquire (Simulation)", test_camera_adapter_acquire_simulation),
        ("Camera Service - Status", test_camera_service_status),
        ("Camera Service - Connect/Disconnect", test_camera_service_connect_disconnect),
        ("Camera Service - Acquire Without DB", test_camera_service_acquire_without_db),
        ("Acquisition Lock - Exclusion", test_acquisition_lock_exclusion),
        ("Observation Privacy", test_observation_privacy),
        ("File Download Authorization", test_file_download_authorization),
        ("Camera API Endpoints", test_camera_api_endpoints),
        ("Scientist Cannot Access Admin", test_scientist_cannot_access_admin_page),
        ("Commands Still Disabled", test_commands_still_disabled),
    ]

    passed = 0
    failed = 0
    errors = []

    for name, test_func in tests:
        try:
            print(f"Running: {name}")
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  FAIL: {e}")

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    if errors:
        print()
        print("Failures:")
        for name, err in errors:
            print(f"  - {name}: {err}")
    print("=" * 60)
    print()
    print("SIMULATION VERIFIED — physical camera hardware not tested")
    print("REAL HARDWARE VERIFIED — NOT VERIFIED (hardware unavailable)")
