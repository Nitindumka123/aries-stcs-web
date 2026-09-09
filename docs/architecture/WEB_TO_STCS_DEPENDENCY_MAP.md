# Web → STCS Dependency Map (Phase 4, authoritative)

## Coupling 1 — camera driver (direct module import)
stcs_web/routes_camera.py → stcs_web/camera_service.py → stcs_web/camera_adapter.py
  → sys.path += <root>/stcs_v1/src → drivers.camera.science_driver.ScienceCameraDriver
  → PURPOSE: PIXIS/LightField acquisition in simulation-or-hardware mode; graceful
  fallback when LightField absent. Evidence: camera_adapter.py:93-99.
  PRESERVE: stcs_v1/src/drivers/camera/science_driver.py path EXACTLY.

## Coupling 2 — telescope config (filesystem read)
stcs_web/observatory.py + stcs_web/telemetry.py → open(<root>/stcs_v1/config/limits.json,
  settings.json, state.json) → PURPOSE: limits/thresholds/state truth (never invented
  in web). Evidence: telemetry.py:44. PRESERVE: stcs_v1/config/*.json paths.

## Coupling 3 — telemetry/command network boundary
stcs_web/command_service.py → stcs_web/control_client.py (websockets) →
  ws://TELEMETRY_WS_HOST:11112 (STCS V1 telemetry_server.py + telemetry_worker.py)
stcs_web/command_service.py → stcs_web/alpaca_client.py (urllib HTTP) →
  http://ALPACA_HOST:11111 (STCS V1 alpaca_server.py)
stcs_web/telemetry.py → UDP weather :12344 (STCS V1 weather_worker.py → telemetry WS)
PURPOSE: read-only live/stale/disconnected telemetry; command intents validated
server-side, never executed (STCS_COMMANDS_ENABLED=0). No browser→hardware path.

## Non-couplings (comment/docstring only — no runtime effect)
command_service.py:89 ("matching stcs_v1 MotionState"), observatory.py:8,144,
telemetry.py docstrings, templates/system.html:76.

## Architecture
Browser → FastAPI (auth→RBAC→routes/services) → integration layer
(camera_adapter/control_client/alpaca_client/telemetry) → STCS V1
(driver/config/workers) → drivers/serial/Arduino/relay → telescope.
No second implementation of RA/DEC/LST/encoder/slew/safety math in web layer
(observatory.py holds only display thresholds from limits.json).
