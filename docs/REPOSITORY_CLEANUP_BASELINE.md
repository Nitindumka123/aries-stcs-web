# REPOSITORY CLEANUP BASELINE — Phase 0 Freeze

Date (UTC): 2026-09-09
Branch: main
Commit: de8306d "Initial ARIES STCS web modernization"
STCS_COMMANDS_ENABLED: 0 (must remain 0)
Physical hardware: NOT TESTED

## Git status (freeze)
- Branch `main`, up to date with origin/main.
- Uncommitted MODIFIED (web QA fixes, verified in Prompts 1-4):
  .env.example, check_db.py, check_pg.py,
  stcs_web/auth.py, auth_constants.py, database.py, main.py, obs_store.py,
  observatory.py, pages.py, routes.py, static/app.css, static/app.js,
  telemetry.py, templates/admin.html, base.html, camera.html, control.html,
  login.html, observations.html, system.html
- Uncommitted DELETED (prior junk removal, working tree clean):
  query, run_review.ps1, run_smoke.ps1, shot_*.png (8), shot_review.py,
  shot_smoke.py, "starting evrytime.txt", stcs_web/templates/dashboard.html,
  test_export.ps1, test_phase2.ps1, test_roles.ps1, test_routing.py,
  test_routing2.py, test_session.ps1, test_timing.ps1, test_ui_struct.ps1
- Untracked (new web product + QA evidence, to be organized):
  docs/ (6 QA reports), stage_a.py,
  stcs_web/alpaca_client.py, camera_adapter.py, camera_service.py,
  command_defs.py, command_service.py, control_client.py, control_lock.py,
  rate_limit.py, routes_camera.py,
  test_auth.py, test_camera.py, test_db_rbac.py, test_db_rbac2.py,
  test_export.py, test_export_direct.py, test_export_final.py,
  test_export_full.py, test_obs_e2e.py, test_packages.py, test_rbac.py,
  test_rbac2.py, test_session.py, verify_env.py, verify_pg.py
- STCS V1 gate: `git diff --name-only -- stcs_v1/` = EMPTY. No staged diff. No untracked under stcs_v1/.

## Repository tree (project files, excl .venv/__pycache__/__MACOSX)
Root: .env, .env.example, .gitignore, ARCHITECTURE.md, DEVELOPMENT_PLAN.md,
DEVELOPMENT_RULES.md, PHASE1_ARCHITECTURE_CHECK.md, PROJECT_CONTEXT.md,
PROJECT_MAP.md, README.md, SECURITY_MODEL.md, SETUP.md, check_db.py,
check_pg.py, stage_a.py, test_*.py (13), verify_*.py (2)
stcs_web/: 18 .py modules + templates (7 html) + static (css/js/svg)
stcs_v1/: 89 tracked files — src/{core(10),drivers(10),workers(9),ui(20+),main.py},
  config/*.json (4), tests/, utils(4), requirements.txt
docs/: 6 QA reports
Tracked junk: __MACOSX/ (118 AppleDouble `._` files)

## File counts
- Total on disk incl .venv: ~12031 files, 4878 .py, 1479 .pyc, 192 __pycache__
- Project .py (excl venv): stcs_web 18, stcs_v1 ~60, root tests/utils ~20
- Templates: 7 (stcs_web/templates/*.html)
- Static: app.css, app.js, favicon.svg
- Tests: root test_*.py x13 + stcs_v1/tests + test_camera.py (entry guarded)
- Config: .env (ignored), .env.example (tracked), stcs_v1/config/*.json (4)
- Docs: root *.md x9 + docs/*.md x6
- Generated: stcs_v1/src/build/* (untracked, ignored), stcs_v1/src/dist/STCS_V1.exe (untracked, ignored),
  __pycache__, .pytest_cache, fallback_creds.txt (ignored)
- Binaries: STCS_V1.exe (generated), 50 .exe in .venv/Scripts (venv only)

## Application entry points
- WEB (authoritative after cleanup): `python -m stcs_web` (TO BE CREATED via stcs_web/__main__.py);
  current working: `python stcs_web/main.py` / `uvicorn stcs_web.main:app --host 127.0.0.1 --port 8000`.
  Root `/` redirects to /api/login or /app/control. Login at /api/login.
- DESKTOP (legacy, preserved, NOT primary): `python stcs_v1/src/main.py` (QApplication + MainWindow);
  frozen binary stcs_v1/src/dist/STCS_V1.exe (generated). Must NOT be reachable from web startup path.
- TESTS: test_camera.py has `if __name__ == "__main__"` runner; others are top-level scripts run via `python <file>`.
- UTILS: stcs_v1/utils/*.py (calibration, port finder, weather, serial diagnostic); root check_db.py/verify_pg.py diagnostics.

## Dependencies (.venv pip list, abbreviated)
fastapi 0.141.1, starlette 1.6.0, uvicorn (via Scripts), Jinja2 3.1.6, python-multipart 0.0.32,
psycopg2-binary 2.9.12, bcrypt 5.0.0, python-dotenv 1.2.3, httpx 0.28.1, websockets 17.1,
openpyxl 3.1.5, fpdf2 2.8.8, pillow 12.3.0, numpy 2.5.3, astropy 8.0.1, opencv-python 5.0.0.93,
pypylon 26.7, pyserial 3.5, pynmea2 1.19.0, pythonnet 3.1.0, pywin32 312, PyQt6 6.11.0,
pytest 9.1.1, requests 2.34.2. NO root requirements.txt / pyproject.toml / setup.py (gap to fix).

## Test command
No unified runner. Manual: `python test_auth.py`, `python test_camera.py`, etc. from repo root.
3 known TestClient CSRF/form-cookie harness failures (infra limitation, not software defect).

## Configuration
- .env (local, ignored): TELESCOPE_MODE, ALPACA_HOST/PORT, DB_HOST/PORT/NAME/USER/PASSWORD (dev),
  SESSION_SECRET (dev default), STCS_COMMANDS_ENABLED=0, WEB_HOST/PORT, WEATHER_PORT, TELEMETRY_WS_*.
- .env.example (tracked, placeholders only).
- stcs_v1/config/: settings.json, limits.json, state.json, slip_calibration.json (read by web telemetry).

## Runtime ports
- Web: 8000 (WEB_HOST 127.0.0.1 / WEB_PORT 8000)
- Alpaca HTTP: 11111 (STCS V1 alpaca_server)
- Telemetry WS: 11112 (STCS V1 telemetry_server)
- Weather UDP: 12344 (STCS V1 weather_worker → telemetry)
- PostgreSQL: 5432 (stcs_observatory)

## STCS integration endpoints (consumed by web)
- HTTP Alpaca via stcs_web/alpaca_client.py → http://ALPACA_HOST:11111
- WS telemetry via stcs_web/control_client.py + telemetry.py → ws://TELEMETRY_WS_HOST:11112
- Filesystem: stcs_v1/config/*.json read by stcs_web/telemetry.py
- Runtime import: stcs_v1/src/drivers/camera/science_driver.py via stcs_web/camera_adapter.py sys.path insert

## Known generated files
__pycache__/, *.pyc, .pytest_cache/, stcs_v1/src/build/, stcs_v1/src/dist/, __MACOSX/ (tracked junk),
stcs_web/fallback_creds.txt (ignored), crash_log.txt (possible, from stcs_v1 main crash handler).

## Cleanup risks
1. stcs_v1/ must stay untouched (git diff gate). No deletion under stcs_v1/.
2. science_driver.py + config JSONs are load-bearing for web — preserve paths.
3. Test scripts bootstrap PROJECT_ROOT from __file__ — fix bootstrap when moving to tests/.
4. Hardcoded dev DB password in untracked test scripts — do not commit secrets; switch to env.
5. Flat stcs_web/ layout is proven — do NOT repackage into app/ subpackages (over-engineering risk).
6. README rewrite must match the REAL verified startup command.
