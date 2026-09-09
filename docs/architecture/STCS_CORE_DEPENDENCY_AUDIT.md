# STCS Core Dependency Audit (Phase 3)

Rule: do NOT delete authoritative code because it lives under stcs_v1. Default: stcs_v1 untouched.

## AUTHORITATIVE / REQUIRED (preserve)
- src/core/astrometry.py — LST/HRA/AltAz/airmass math
- src/core/dome_geometry.py — dome azimuth math (used by dome_sync)
- src/core/legacy_decoder.py — encoder→RA/DEC port of aries1m.c
- src/core/motion_state.py — relay payload protocol, interlocks/limits
- src/core/safety.py — altitude guard (imports motion_state)
- src/core/slew_engine.py — waypoint/slew planner (imports motion_state, astrometry, safety)
- src/drivers/camera/science_driver.py — PIXIS/LightField driver; ONLY module directly
  imported by web (camera_adapter.py:99). LOAD-BEARING.
- src/drivers/mount/mount_coordinator.py — RA/DEC/dome orchestration (smart_serial)
- src/drivers/mount/smart_serial.py, control_serial.py — Arduino relay protocol
- src/drivers/gps/gps_driver.py — GPS serial
- src/workers/alpaca_server.py (:11111), telemetry_server.py (:11112),
  telemetry_worker.py, weather_worker.py (:12344) — network boundary web depends on
- src/workers/indi_telescope_driver.py — pure-python INDI server (no PyQt)
- config/*.json — limits/settings/state/slip_calibration read by web telemetry
- stcs_v1/utils/* — calibration_tool, find_aurdino_port, get_weather_data, serial_diagnostic

## MIXED (PyQt + real logic — DO NOT SPLIT, preserve as-is)
- src/core/dome_sync.py — QThread + dome math (imports dome_geometry)
- src/core/simulation_engine.py — QThread + sidereal/motion sim (imports motion_state)

## DESKTOP-ONLY (PyQt UI — preserved in place per stcs_v1-untouched rule)
- src/main.py (QApplication entry), src/ui/** (main_window, styles, components x10,
  tabs x4 [EMPTY], widgets x2 [EMPTY], windows x3). motion_panel imports legacy_decoder
  (UI→core direction only; core never imports UI).

## EMPTY placeholders (0 bytes, preserved — deleting would dirty stcs_v1 gate)
core/auto_guider.py, drivers/mount/{dec,dome,mount,ra}_controller.py,
drivers/sensors/weather_station.py, ui/tabs/*, ui/widgets/*, workers/guider_worker.py,
tests/test_alpaca_client.py. Left in place: zero behavioral effect, avoids stcs_v1 diff.

## TESTS / UTILS (preserved)
stcs_v1/tests/* hardware + math tests; UI/relay_test_gui.py dev GUI.

## Conclusion
Every retained stcs_v1 module is justified: either web-required (driver/config/workers),
or authoritative control/science, or desktop shell preserved for physical commissioning
fallback. NOTHING under stcs_v1/ is deleted or moved in this cleanup.
