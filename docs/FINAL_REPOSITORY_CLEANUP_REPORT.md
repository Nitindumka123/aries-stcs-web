# Final Repository Cleanup Report (Phases 0–50)

## 1. Executive summary
The repository is now web-first: `python -m stcs_web` is the single documented startup,
README no longer presents the PyQt desktop GUI as the product, root contains only
entry + contracts, tests live in `tests/`, diagnostics in `scripts/`, docs in `docs/`.
STCS V1 is byte-untouched (`git diff --name-only -- stcs_v1/` = EMPTY). One P1 defect
(broken lifespan → uvicorn could not boot) was found and fixed; four P3 test-script bugs
fixed test-side only; one P3 harness limitation documented. No scientific, control,
safety, protocol, calibration, or observation-data changes. STCS_COMMANDS_ENABLED=0.
Physical hardware NOT tested.

## 2. Before architecture
Root mixed product code, 13 loose test scripts, 9 loose docs (README described ONLY the
desktop GUI), no `python -m stcs_web` entry, no root requirements, `__MACOSX/` junk
tracked (118 files), stray `stcs_web/_/` package, duplicate test variants, hardcoded dev
passwords in scripts, no STCS_COMMANDS_ENABLED in `.env.example`.

## 3. After architecture
See `docs/FINAL_REPOSITORY_STRUCTURE.md`. Web primary; STCS V1 preserved baseline;
tests/scripts/docs separated; root = README + requirements + pyproject + env contract + ignore.

## 4. Desktop GUI components removed
`__MACOSX/` (118 AppleDouble files), `stcs_web/_/_init__.py` (stray typo package).
Nothing under `stcs_v1/` removed — desktop shell preserved in place per the
stcs_v1-untouched rule (see `docs/architecture/STCS_CORE_DEPENDENCY_AUDIT.md`).

## 5. STCS components preserved
All 89 tracked files: core math/safety (astrometry, legacy_decoder, motion_state,
safety, slew_engine, dome_geometry + MIXED dome_sync/simulation_engine kept whole),
drivers (science_driver — web-imported, mount_coordinator, smart/control_serial,
gps_driver), network workers (alpaca :11111, telemetry WS :11112, weather UDP :12344),
config JSONs, utils, tests. See `docs/PRESERVED_STCS_COMPONENTS.md`.

## 6. Files removed (131 + 23 prior working-tree deletions kept)
131: __MACOSX x118, stcs_web/_/_init__.py, check_pg.py (password brute-forcer),
stage_a.py, verify_env.py, test_packages.py, test_export{x3 dupes}, test_rbac.py (dupe),
test_db_rbac.py (dupe), PROJECT_MAP.md (predates web app). Evidence per file in
`docs/REMOVED_OBSOLETE_COMPONENTS.md`. 23 prior deletions (screenshots, temp ps1/py,
orphaned dashboard.html, "starting evrytime.txt", query) verified consumer-free, kept.

## 7. Files moved (22)
tests/: test_auth, test_camera, test_session, test_obs_e2e, test_export_full,
test_rbac2, test_db_rbac2 (+ new conftest.py). scripts/: check_db, verify_pg.
docs/: 7 root docs → architecture/security/operations/qa homes; 6 QA reports → docs/qa/.

## 8. Files renamed
docs/operations/SETUP.md → SETUP_legacy.md (superseded by OPERATIONS.md, kept for history).

## 9. Files consolidated
4 export variants → tests/test_export_full.py; 2 RBAC → test_rbac2.py;
2 DB-RBAC → test_db_rbac2.py. No web-app code merged (inspected lookalikes are
semantically distinct with live consumers).

## 10. Dependency analysis
`docs/architecture/DEPENDENCY_MAP.md`: stcs_web has ZERO `import stcs_v1`; only
camera_adapter.py sys.path→science_driver + telemetry.py config-JSON reads.
`WEB_TO_STCS_DEPENDENCY_MAP.md` is the integration contract. `ENTRYPOINT_AUDIT.md`:
normal startup can never launch PyQt (no Qt in web import closure; verified by grep).

## 11. Web entry point
`python -m stcs_web` (new `stcs_web/__main__.py`, delegates to `stcs_web.main:app`).
Equivalents: `python stcs_web/main.py`, `uvicorn stcs_web.main:app`.

## 12. Startup behavior (verified live)
Uvicorn boots, lifespan runs (DB init, command/camera services), `/api/login` 200 with
CSRF + password field, `/api/health` ok, no PyQt window, DB connected, commands disabled.

## 13. Test organization
`tests/` + conftest.py (root insert for pytest). Scripts run as `python tests/<name>.py`
from root (bootstrap fixed for new location). Failing assertions kept, never deleted.

## 14. Documentation organization
architecture/ (legacy ARCHITECTURE.md + WEB_ARCHITECTURE.md + 4 audit maps),
security/, operations/ (OPERATIONS.md + legacy setup), deployment/, qa/ (Prompts 1–4),
commissioning/ (reserved), root/topical dev docs.

## 15. Configuration cleanup
New root `requirements.txt` (12 web deps, pinned to verified venv) + `pyproject.toml`;
`.env.example` gained documented `STCS_COMMANDS_ENABLED=0`; `.gitignore` gained
`__MACOSX/`, `crash_log.txt`. `.env` stays local/ignored.

## 16. Generated artifact cleanup
`__MACOSX/` purged from source control. `__pycache__/*.pyc/.pytest_cache/build/dist/
fallback_creds.txt/.env` already ignored; `stcs_v1/src/build+dist` (untracked,
regenerable PyInstaller output) left on disk, out of git.

## 17. Security cleanup
Hardcoded dev DB password removed from all tests/scripts (env-guard with clear
error) and
redacted in QA docs. No password/token logging in app. CSRF/RBAC/privacy/audit
verified by rerun. `.env` ignored; `.env.example` placeholders only.

## 18. Scientific-integrity verification
No formula/constant/unit/sign/precision/timing/threshold/state/exception/payload/
protocol/calibration change: only `stcs_web/main.py` lifespan structure fixed
(yield+shutdown restored to lifespan; validator is checks-only). STCS V1 diff EMPTY.

## 19. STCS integrity verification
`git diff --name-only -- stcs_v1/` = EMPTY (plus no staged/untracked changes under it).

## 20. PostgreSQL preservation
No drop/recreate/truncate. Verified live: users, observations, files, audit rows intact;
test runs only INSERT clearly-labeled test rows.

## 21. Observation preservation
Privacy re-verified after moves: S1⊄Admin data, cross-user detail None, cross-user
delete Unauthorized, file download owner/admin-only, exports privacy-filtered.

## 22. Regression results
- tests/test_auth.py PASS · tests/test_session.py PASS · tests/test_camera.py 12/13
  (1 documented harness/contract failure, §24) · tests/test_rbac2.py PASS
  · tests/test_obs_e2e.py PASS · tests/test_export_full.py PASS (CSV/XLSX/PDF+privacy)
  · tests/test_db_rbac2.py PASS · live boot PASS · 62 endpoints inventoried ·
  24 frontend API refs all resolve · all 17 stcs_web modules import.

## 23. Remaining legacy components and reasons
stcs_v1 desktop shell (commissioning fallback, untouched); EMPTY placeholders (gate
hygiene); `lst_hours_fallback`/`juliandate` in observatory.py — DISPLAY-ONLY LST/JD
fallback labeled FALLBACK-UTC, never in command path (reviewed §Phase 27, retained).

## 24. Remaining known limitations
1. test_camera_api_endpoints posts bodiless to CSRF-JSON `/api/camera/connect`
   (harness/contract; route + validation correct, frontend sends JSON+CSRF).
2. QA-known TestClient CSRF/form-cookie session-persistence limits (unchanged).
3. Physical hardware untested; STCS_COMMANDS_ENABLED=0.

## 25. Final repository tree
See `docs/FINAL_REPOSITORY_STRUCTURE.md`.

## 26. Recommended future development rules
1. `stcs_v1/` is read-only truth — never edit for cleanliness.
2. Web never reimplements telescope math for control; display fallbacks must stay labeled.
3. One startup: `python -m stcs_web`. No new launchers.
4. No secrets in code/docs; DB_PASSWORD via environment.
5. Never delete/skip a failing test to get green; fix or document.
6. Keep STCS_COMMANDS_ENABLED=0 until on-site commissioning authorizes otherwise.

## Defects found during cleanup
- P1 FIXED: `stcs_web/main.py` lifespan lost its `yield` (+shutdown) into
  `_validate_production_config` during QA evolution → uvicorn boot crashed
  (`'coroutine' object is not an async iterator`). Restored; live boot verified.
- P3 FIXED (test-only): test_rbac2/test_obs_e2e re-cleared sys.modules after patching
  (patch never took effect); test_export_full `patched_get_conn` typo;
  test_obs_e2e imported removed `export_observations_csv` (replaced with CSV-shape
  check over the same store data; canonical format coverage in test_export_full).
- P3 DOCUMENTED: camera API-endpoints harness call vs CSRF-JSON contract (§24.1).

## Test-path relocation map (for QA report readers)
test_auth.py → tests/test_auth.py · test_camera.py → tests/test_camera.py ·
test_session.py → tests/test_session.py · test_obs_e2e.py → tests/test_obs_e2e.py ·
test_export_full.py → tests/test_export_full.py · test_rbac2.py → tests/test_rbac2.py ·
test_db_rbac2.py → tests/test_db_rbac2.py · check_db.py → scripts/check_db.py ·
verify_pg.py → scripts/verify_pg.py.
