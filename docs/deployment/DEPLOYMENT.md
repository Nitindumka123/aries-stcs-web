# Deployment (software-only; no physical commissioning claimed)

## Target
Single host running FastAPI (`uvicorn stcs_web.main:app`) + PostgreSQL.
Serve behind a reverse proxy with TLS for any non-localhost use; then set
`SESSION_SECURE_COOKIE=true` and `ENABLE_HSTS=true`.

## Checklist
1. `pip install -r requirements.txt` (web deps only).
2. PostgreSQL `stcs_observatory` reachable; strong `DB_PASSWORD` via environment.
3. Unique random `SESSION_SECRET` via environment (never the dev default).
4. `STCS_COMMANDS_ENABLED=0` (physical motion requires separate on-site authorization).
5. `CORS_ORIGINS` restricted to the real origin(s).
6. `.env` present locally, never committed; `.env.example` is the contract.

## What NOT to deploy
- `stcs_v1/src/main.py` (desktop GUI) — not part of the web deployment.
- `__MACOSX/`, `stcs_v1/src/build/`, `stcs_v1/src/dist/` — removed/ignored artifacts.
- `tests/`, `scripts/` — diagnostics, not runtime.
