# ARIES 104 cm Sampurnanand Telescope — Web Observatory Platform

Modern web application for the 104 cm Sampurnanand Telescope (ARIES).
Authenticated browser interface over the proven STCS V1 telescope-control core.

## PRIMARY APPLICATION: Web Observatory Platform

The supported product is the **web application** in `stcs_web/`
(FastAPI backend + authenticated workspaces + PostgreSQL).

### START (authoritative)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in DB_PASSWORD, SESSION_SECRET
python -m stcs_web
```

Equivalents: `python stcs_web/main.py`, or
`uvicorn stcs_web.main:app --host 127.0.0.1 --port 8000`.

### OPEN

- Login: http://127.0.0.1:8000/api/login
- Control workspace: http://127.0.0.1:8000/app/control (after login)
- API docs: http://127.0.0.1:8000/api/docs
- Default dev users come from `ADMIN_USERNAME`/`SCIENTIST_USERNAME` in `.env`
  (created in PostgreSQL on first start).

### DO NOT START (legacy desktop GUI)

`python stcs_v1/src/main.py` launches the historical PyQt6 desktop GUI.
It is **preserved untouched** as the authoritative STCS V1 baseline for
physical commissioning fallback — it is NOT the supported startup path.
Running it by accident is a workflow error, not a product feature.
See `docs/architecture/STCS_CORE_DEPENDENCY_AUDIT.md`.

## How it fits together

```
Browser → FastAPI (auth → RBAC → routes/services) → STCS integration layer
→ STCS V1 driver/config/workers → serial/Arduino/relay → telescope
```

- The browser NEVER touches serial ports, Arduino, relays, motors, or camera hardware.
- Telescope commands are validated server-side and stay disabled unless
  `STCS_COMMANDS_ENABLED=1` (default and required for all software work: `0`).
- The web backend reads live telemetry from the STCS V1 Alpaca server (:11111)
  and WebSocket telemetry server (:11112), plus `stcs_v1/config/*.json`.
- Camera acquisition reuses `stcs_v1` `ScienceCameraDriver` via
  `stcs_web/camera_adapter.py`, with graceful simulation fallback.

## Repository layout

- `stcs_web/` — authoritative web application (flat, proven layout; see `main.py`)
- `stcs_v1/` — authoritative STCS V1 telescope-control baseline (**do not modify**)
- `tests/` — auth, RBAC, session, camera, export, observation E2E checks
- `scripts/` — local diagnostics (`check_db.py`, `verify_pg.py`)
- `docs/` — architecture, security, operations, deployment, commissioning, QA
- `requirements.txt` — web dependencies · `stcs_v1/requirements.txt` — legacy desktop
- `.env.example` — config contract (placeholders only) · `.env` — local, never committed

## Safety

- `STCS_COMMANDS_ENABLED=0` always for software work. No physical telescope
  operations are performed or tested from this repository state.
- Physical hardware has NOT been tested. Commissioning steps live in
  `docs/commissioning/` (to be executed on-site only).

## Docs

- `docs/operations/OPERATIONS.md` — run, configure, troubleshoot
- `docs/deployment/DEPLOYMENT.md` — deployment notes
- `docs/architecture/DEPENDENCY_MAP.md` — what imports what
- `docs/architecture/WEB_TO_STCS_DEPENDENCY_MAP.md` — web→STCS contract
- `docs/qa/` — QA campaign evidence (Prompts 1–4, P0=P1=P2=P3=0)
