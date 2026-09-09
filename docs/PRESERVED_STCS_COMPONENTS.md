# Preserved STCS Components (Phase 38)

Future maintainer: THIS IS NOT "old GUI code". Do not delete. Rationale per module:

## Control / science core (src/core/)
- astrometry.py — LST/HRA/AltAz/airmass. Web never reimplements; sole source.
- legacy_decoder.py — encoder→RA/DEC (aries1m.c port). Sole source.
- motion_state.py — relay payloads, interlocks, limits. Sole source.
- safety.py — altitude guard. Sole source.
- slew_engine.py — waypoint/slew planner. Sole source.
- dome_geometry.py — dome math backing dome_sync.
- dome_sync.py / simulation_engine.py — MIXED QThread+logic; kept whole (no split).
- gps_event_logger.py — GPS serial logging.

## Drivers (src/drivers/)
- camera/science_driver.py — web-imported (camera_adapter.py:99). LOAD-BEARING.
- mount/mount_coordinator.py, smart_serial.py, control_serial.py — Arduino relay path.
- gps/gps_driver.py — GPS serial.

## Workers = network boundary (src/workers/)
- alpaca_server.py :11111, telemetry_server.py :11112, telemetry_worker.py,
  weather_worker.py :12344, indi_telescope_driver.py, camera/gps/guider workers,
  udp_broadcaster.py — web consumes the servers over the network; workers preserved.

## Desktop shell (src/ui/ + src/main.py) — preserved, not primary
Historical PyQt6 GUI + frozen EXE build chain. Kept untouched as the
scientist-tested commissioning fallback. README marks it DO NOT START.

## Config / utils / tests
- config/*.json — web telemetry truth (limits/settings/state/slip).
- utils/* — calibration, port finder, weather fetch, serial diagnostic.
- tests/* — hardware + math checks (LegacyDecoder etc.).
- EMPTY placeholders (auto_guider, *_controller x4, weather_station, tabs, widgets,
  guider_worker, test_alpaca_client) — 0 bytes, kept to hold the stcs_v1-untouched gate.
