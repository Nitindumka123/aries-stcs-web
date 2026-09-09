# Final Repository Structure

```
GUI/
├── README.md                  # web-first startup contract
├── requirements.txt           # web deps (authoritative)
├── pyproject.toml             # project metadata + pytest testpaths
├── .env.example               # config contract (placeholders)
├── .gitignore
├── stcs_web/                  # PRIMARY APPLICATION (flat, proven)
│   ├── __main__.py            # `python -m stcs_web`
│   ├── main.py                # FastAPI app + lifespan + routers
│   ├── routes.py pages.py routes_camera.py
│   ├── auth.py auth_constants.py rate_limit.py
│   ├── command_service.py command_defs.py control_client.py
│   ├── alpaca_client.py control_lock.py
│   ├── camera_service.py camera_adapter.py
│   ├── telemetry.py observatory.py
│   ├── database.py obs_store.py
│   ├── templates/ (7 pages) + static/ (css/js/svg)
├── stcs_v1/                   # AUTHORITATIVE STCS BASELINE — DO NOT MODIFY
│   ├── src/{core,drivers,workers,ui,main.py}
│   ├── config/*.json  tests/  utils/  requirements.txt
├── tests/                     # conftest + auth/session/camera/rbac/export/obs-e2e
├── scripts/                   # check_db.py verify_pg.py (need DB_PASSWORD env)
├── docs/
│   ├── REPOSITORY_CLEANUP_BASELINE.md  FINAL_REPOSITORY_STRUCTURE.md
│   ├── REMOVED_OBSOLETE_COMPONENTS.md  PRESERVED_STCS_COMPONENTS.md
│   ├── FINAL_REPOSITORY_CLEANUP_REPORT.md  REPOSITORY_CLEANUP_STATE.md
│   ├── architecture/ (ARCHITECTURE.md=legacy, WEB_ARCHITECTURE.md, DEPENDENCY_MAP.md,
│   │   STCS_CORE_DEPENDENCY_AUDIT.md, WEB_TO_STCS_DEPENDENCY_MAP.md, ENTRYPOINT_AUDIT.md)
│   ├── security/SECURITY_MODEL.md  operations/{OPERATIONS.md, SETUP_legacy.md}
│   ├── deployment/DEPLOYMENT.md  commissioning/  qa/ (Prompts 1-4 evidence)
│   ├── DEVELOPMENT_RULES.md  DEVELOPMENT_PLAN.md  PROJECT_CONTEXT.md
```

## Purpose per directory
- stcs_web: the product. stcs_v1: the telescope truth. tests: product checks.
- scripts: human-run diagnostics. docs: the map. Root: entry + contracts only.
