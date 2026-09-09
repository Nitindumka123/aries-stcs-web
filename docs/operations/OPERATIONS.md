# Operations

## Start
```powershell
.\.venv\Scripts\activate
python -m stcs_web
```
Open http://127.0.0.1:8000/api/login.

## Configure (.env)
Copy `.env.example` → `.env`. Required for real use: `DB_PASSWORD`,
`SESSION_SECRET`. Defaults: `WEB_HOST=127.0.0.1`, `WEB_PORT=8000`,
`TELESCOPE_MODE=REAL`, `STCS_COMMANDS_ENABLED=0` (keep 0).

## Database (PostgreSQL)
`DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD` → `stcs_observatory`.
Health: `python scripts/check_db.py`, schema/data: `python scripts/verify_pg.py`
(both require `DB_PASSWORD` in the environment).

## STCS companions (optional, for live telemetry)
The web app degrades honestly to Disconnected/Stale without them:
- STCS V1 Alpaca server on :11111 (`ALPACA_HOST/ALPACA_PORT`)
- STCS V1 telemetry WebSocket on :11112 (`TELEMETRY_WS_HOST/TELEMETRY_WS_PORT`)
- Weather UDP on :12344 (`WEATHER_PORT`)

## Tests
```powershell
$env:DB_PASSWORD = "<local dev password>"   # never committed
python tests/test_auth.py
python tests/test_session.py
python tests/test_camera.py
python tests/test_rbac2.py
python tests/test_export_full.py
python tests/test_obs_e2e.py
```
Known limitation: 3 TestClient CSRF/form-cookie assertions fail due to the
test harness (session cookie persistence), not the app — see docs/qa/.

## Troubleshooting
- Login loops → check `SESSION_SECRET` set, cookies enabled, `/api/login` reachable.
- Empty history → PostgreSQL down; app shows honest empty state, check DB vars.
- Camera unavailable → LightField absent is normal; simulation mode covers software QA.
- Telemetry Disconnected → STCS companion servers not running; software-only mode.
