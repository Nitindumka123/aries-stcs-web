# Dependency Map (Phase 2)

Method: full-repo grep for `import`, `from`, `importlib`, `sys.path`, subprocess/CLI refs,
config/env refs, template/JS route refs. Evidence over filename intuition.

## stcs_web internal graph
main.py (absolute `stcs_web.*` imports) → routes.py, routes_camera.py, pages.py,
database.py, obs_store.py, command_service.py, camera_service.py
routes.py → auth.py, database.py, command_service.py, command_defs.py, rate_limit.py
pages.py → auth.py, observatory.py, obs_store.py, command_defs.py, routes.py (CSRF helpers),
  camera_service.py (lazy), database.py (lazy)
routes_camera.py → auth.py, obs_store.py, camera_service.py (lazy)
command_service.py → telemetry.py, obs_store.py, control_lock.py, command_defs.py,
  control_client.py, alpaca_client.py, observatory.py (lazy)
camera_service.py → camera_adapter.py, obs_store.py, observatory.py (lazy)
observatory.py → telemetry.py, control_lock.py
obs_store.py → database.py
auth.py → database.py
Leaf (no internal imports): alpaca_client, auth_constants, command_defs, control_client,
control_lock, database, rate_limit, telemetry.

## stcs_web → stcs_v1 coupling (ONLY two code-level points)
1. stcs_web/camera_adapter.py:93-99 — inserts `<root>/stcs_v1/src` into sys.path,
   then `from drivers.camera.science_driver import ScienceCameraDriver`. ONLY direct module import.
2. stcs_web/telemetry.py:44 — `STCS_CONFIG_DIR = <root>/stcs_v1/config`; reads limits.json,
   settings.json, state.json via open(). No Python import.
All other stcs_v1 mentions are comments/docstrings/HTML text (command_service.py:89,
observatory.py:8,144, alpaca_client.py docstring, system.html:76).

## Deletion safety table (non-stcs_v1 candidates)
- stcs_web/_/_init__.py: CLASS H (stray typo package, 0 bytes). Imported by: none
  (grep `stcs_web._` = no hits). Imports: none. SAFE TO DELETE.
- __MACOSX/: CLASS J/H (AppleDouble junk, 118 tracked files). Imported by: none.
  Referenced by: none. SAFE TO REMOVE from source control.
- check_pg.py: CLASS H (password brute-forcer). Imported by: none. SAFE TO DELETE.
- stage_a.py: CLASS K (one-shot listing). Imported by: none. SAFE TO DELETE.
- verify_env.py: CLASS K (trivial env echo). Imported by: none. SAFE TO DELETE.
- test_packages.py: CLASS K/G (import-availability check). Imported by: none. SAFE TO DELETE.
- test_export.py / test_export_direct.py / test_export_final.py: CLASS I (dupes of
  test_export_full.py, most complete). Imported by: none. SAFE TO DELETE after keeping canonical.
- test_rbac.py: CLASS I (dupe of test_rbac2.py). SAFE TO DELETE after keeping canonical.
- test_db_rbac.py: CLASS I (dupe of test_db_rbac2.py). SAFE TO DELETE after keeping canonical.
- check_db.py, verify_pg.py: CLASS G (DB diagnostics). Imported by: none. KEEP as scripts/.
- test_auth.py, test_camera.py, test_session.py, test_obs_e2e.py, test_export_full.py,
  test_rbac2.py, test_db_rbac2.py: CLASS E. KEEP, move to tests/ with fixed bootstrap.
- Root docs ARCHITECTURE.md etc: CLASS D. KEEP content, reorganize under docs/.
- PROJECT_MAP.md: CLASS H (predates stcs_web/, omits web app). SAFE TO DELETE (superseded).
- stcs_v1/**: CLASS A/C. DO NOT DELETE (Phase 18 gate). All preserved.

## Frontend dependency note
templates/*.html → static/app.css + static/app.js → /api/* routes in routes.py,
routes_camera.py, pages.py. Verified no orphaned dashboard.html (already deleted).
