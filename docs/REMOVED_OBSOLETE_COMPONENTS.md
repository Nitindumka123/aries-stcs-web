# Removed / Deleted Components (Phase 37)

## __MACOSX/ — 118 tracked AppleDouble files — REMOVED
WHY: macOS archive-extraction metadata (`._*`), zero code/data content.
DEPENDENCY: grep/import refs = none; no consumer in any .py/.md/.ps1.
SAFE: no runtime, build, or doc references. VERIFICATION: `git ls-files` no longer lists them.

## stcs_web/_/_init__.py — stray 0-byte typo package — REMOVED
WHY: `_init__.py` (not `__init__.py`); never a valid package; 0 bytes.
DEPENDENCY: `stcs_web._` imported by nothing (repo-wide grep = no hits).
SAFE: nothing imports it. VERIFICATION: full `stcs_web` import sweep passes after removal.

## check_pg.py — password brute-forcer — REMOVED
WHY: tried 10 hardcoded passwords via psql; superseded by env-based config + scripts/check_db.py.
DEPENDENCY: imported by none. SAFE: standalone script. No replacement (anti-pattern).

## stage_a.py / verify_env.py / test_packages.py — one-shot temp scripts — REMOVED
WHY: K-class: repo listing echo, env echo, import-availability check. No product value.
DEPENDENCY: imported by none. SAFE.

## test_export.py / test_export_direct.py / test_export_final.py — dupes — REMOVED
WHY: I-class duplicates of tests/test_export_full.py (most complete: real PG + privacy + 3 formats).
DEPENDENCY: imported by none. REPLACEMENT: tests/test_export_full.py.
VERIFICATION: canonical export test retained and re-run.

## test_rbac.py — dupe — REMOVED (kept tests/test_rbac2.py)
## test_db_rbac.py — dupe — REMOVED (kept tests/test_db_rbac2.py)
WHY: same RBAC assertions via direct DB; one canonical each.
REPLACEMENT: tests/test_rbac2.py, tests/test_db_rbac2.py.

## PROJECT_MAP.md — outdated map — REMOVED
WHY: predates stcs_web/ and docs/; described only legacy desktop tree.
REPLACEMENT: docs/FINAL_REPOSITORY_STRUCTURE.md + docs/architecture/DEPENDENCY_MAP.md.

## Pre-existing working-tree deletions (kept, verified as correct)
query, run_review.ps1, run_smoke.ps1, shot_*.png x8, shot_review.py, shot_smoke.py,
"starting evrytime.txt", stcs_web/templates/dashboard.html (orphaned),
test_export.ps1, test_phase2.ps1, test_roles.ps1, test_routing.py, test_routing2.py,
test_session.ps1, test_timing.ps1, test_ui_struct.ps1 — screenshots/temp scripts/
superseded harness files with no consumers.

## Deliberately NOT removed
- Anything under stcs_v1/ (Phase 18 gate; all preserved, including EMPTY placeholders).
- Duplicate-looking web modules (auth vs routes auth helpers, telemetry vs observatory):
  inspected, semantically distinct, each with live consumers — no merge.
- Failing TestClient assertions: harness limitation, kept + documented, never deleted.
