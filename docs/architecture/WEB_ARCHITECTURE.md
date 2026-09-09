# Web Architecture (authoritative)

`ARCHITECTURE.md` (same folder) is the historical STCS V1 document — kept for reference.
This file describes the CURRENT product: the web observatory platform.

## Layout (intentionally flat)
`stcs_web/` keeps one module per responsibility, no `app/` repackaging: the layout is
proven by QA (P0=P1=0) and repackaging would risk import/behavior drift for zero
scientific gain (see Phase 9 decision in FINAL_REPOSITORY_CLEANUP_REPORT.md).

- `main.py` + `__main__.py` — app factory, middleware, routers, `python -m stcs_web`
- `routes.py`, `pages.py`, `routes_camera.py` — API + workspace pages + camera API
- `auth.py`, `auth_constants.py`, `rate_limit.py` — authN/RBAC/CSRF/rate limits
- `command_service.py`, `command_defs.py`, `control_client.py`, `alpaca_client.py`,
  `control_lock.py` — validated-only command path (disabled by default)
- `camera_service.py`, `camera_adapter.py` — acquisition via STCS ScienceCameraDriver
- `telemetry.py`, `observatory.py` — read-only telemetry + display thresholds
- `database.py`, `obs_store.py` — PostgreSQL access + observations/audit/weather
- `templates/`, `static/` — 7 pages + design system (css/js/svg)

## Request path
Browser → SessionMiddleware → routes → auth/RBAC → service → integration
(STCS driver / Alpaca HTTP / telemetry WS / PostgreSQL) → template/JSON.
Security headers + CSP on all responses; CSRF on state-changing forms.

## STCS boundary
Only `camera_adapter.py` (driver import) and `telemetry.py` (config JSON reads)
reach into `stcs_v1/`. All telescope math/safety/protocol stays in STCS V1.
