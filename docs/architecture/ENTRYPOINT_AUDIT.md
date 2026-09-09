# Entrypoint Audit (Phase 5)

## OLD DESKTOP (legacy, preserved, NOT supported as primary)
- `python stcs_v1/src/main.py` — QApplication + MainWindow (PyQt6). Evidence: stcs_v1/src/main.py.
- `stcs_v1/src/dist/STCS_V1.exe` — PyInstaller frozen GUI (generated, untracked).
- `stcs_v1/build_exe.ps1` — EXE build script.
- `stcs_v1/tests/UI/relay_test_gui.py` — PyQt relay tester (dev only).
- No setup.py / pyproject entry_points / shortcuts / VS Code launch configs found.

## WEB (supported, authoritative)
- `python -m stcs_web` — PRIMARY (created in this cleanup via stcs_web/__main__.py).
- `python stcs_web/main.py` — equivalent direct runner (uvicorn.run in __main__ block).
- `uvicorn stcs_web.main:app --host 127.0.0.1 --port 8000` — deployment form.
- Root `/` → 302 to /api/login or /app/control. Login: http://127.0.0.1:8000/api/login.

## TEST (manual runners)
- `python tests/test_camera.py` (has __main__ guard), `python tests/test_auth.py`, etc.
- pytest discovery via tests/ (no config required; scripts are top-level runnable).

## UTILITY
- `python scripts/check_db.py`, `python scripts/verify_pg.py`, stcs_v1/utils/*.py.

## Verdict
Normal startup path (`python -m stcs_web`) can NEVER launch the PyQt GUI: stcs_web
imports contain zero PyQt6 (only stcs_v1 science_driver import, which is driver-only,
no Qt). Accidental GUI launch requires explicitly running stcs_v1/src/main.py, which
the rewritten README marks DO NOT START.
