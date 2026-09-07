# Phase 1 Architecture Check Report

## A. Actual SessionMiddleware Configuration

From `stcs_web/main.py:38-42`:

```python
app.add_middleware(
    SessionMiddleware,
    session_cookie_name="stcs_session",
    secret_key=os.environ.get("SESSION_SECRET", secrets.token_hex(32)),
)
```

**Explicitly configured parameters:**
- `session_cookie_name = "stcs_session"` — the cookie name used for the session
- `secret_key` — read from environment variable `SESSION_SECRET`; falls back to `secrets.token_hex(32)` (random 64-char hex string) if not set

**Parameters NOT configured (Starlette defaults in effect):**
- `max_age` — **default: browser session** (cookie deleted when browser closes; no persistent session expiration beyond closing the browser)
- `https_only` — **default: False** — session cookie works on both HTTP and HTTPS
- `same_site` — **default: "lax"** — prevents CSRF from other sites while allowing same-site navigation
- `path` — **default: "/""
- `domain` — **default: None**

## B. Local HTTP Development Compatibility

**Yes, local HTTP development on http://127.0.0.1:8000 works correctly with the current configuration.**

- `https_only=False` (the default) means session cookies are sent over both HTTP and HTTPS
- Without forcing `https_only=True`, developers can run the app locally with `python -m stcs_web.main` and log in via `http://127.0.0.1:8000/api/login`
- If `https_only` were forced to `True`, the session cookie would not be transmitted over plain `http://`, breaking local development
- `same_site="lax"` provides reasonable CSRF protection while allowing the login form POST to work from the same origin
- The session secret from `SESSION_SECRET` env var ensures consistent session behavior across server restarts when running locally

## C. Exact Behavior When PostgreSQL Is Unavailable

From `stcs_web/main.py:61-91` (`startup_event()`):

1. `database.init_users_table()` is called within a try/except block
   - Uses `CREATE TABLE IF NOT EXISTS` — additive, never destructive
   - If PostgreSQL connection fails, the exception is caught and printed as a warning
   - The application **continues running** without the database table

2. Default development users are created **as a file-based fallback** (lines 71-91):
   - `ADMIN_USERNAME` (default: "Admin") and `ADMIN_PASSWORD` (default: "Admin@123") hashed with bcrypt
   - `SCIENTIST_USERNAME` (default: "Scientist1") and `SCIENTIST_PASSWORD` (default: "Pass@123") hashed with bcrypt
   - Fallback credentials written to `stcs_web/fallback_creds.txt` in format: `username:bcrypt_hash:role`
   - Each server restart overwrites the file with deterministic hashes from the fixed passwords

3. Authentication fallback path (`database.py:get_user_by_username()`):
   - First attempts PostgreSQL connection
   - On `psycopg2.OperationalError`, `psycopg2.InterfaceError`, or any other exception: falls through to file-based credentials
   - Reads `stcs_web/fallback_creds.txt` if it exists
   - Returns user dict for "Admin" or "Scientist1" with hashed passwords
   - If file doesn't exist or username not found: returns `None`

4. **Result when PostgreSQL is unavailable:**
   - Application starts successfully
   - Login works with development credentials (Admin / Admin@123, Scientist1 / Pass@123)
   - Protected dashboard is accessible after login
   - Logout works
   - All authentication is file-based and temporary

## D. Should fallback_creds.txt Remain Development-Only?

**Yes — it must remain development-only and must not be part of the production architecture.**

**Rationale:**
1. The `.env.example` and `DEVELOPMENT_RULES.md` (RULE 9, RULE 8) explicitly state: "Never hard-code passwords" and "Use environment variables"
2. The combined security model (SECURITY_MODEL.md) requires: "No hard-coded passwords or secrets in source code"
3. For the observatory system, **PostgreSQL must be the authoritative identity/user store** — as stated in PROJECT_CONTEXT.md: "PostgreSQL will be used for the future application/database layer"
4. The fallback is explicitly a startup-time convenience mechanism, not a permanent authentication architecture
5. If PostgreSQL is properly deployed, the fallback path should not be reached; users are created and verified from the database

**The fallback should NOT be:**
- The permanent authentication mechanism
- Committed to version control with real hashes
- The primary way users log in during normal operation

**The fallback CAN/should:**
- Serve as a development convenience for local testing without PostgreSQL
- Be regenerated each server start (which is what the startup event does)
- Include deterministic hashes from the development passwords so Admin / Admin@123 and Scientist1 / Pass@123 always work locally
- Be documented as "development-only" in the project documentation

## E. Is Any Code Change Necessary?

**No code changes are necessary for the session configuration or fallback credentials to function correctly.**

**What exists works as designed:**
- SessionMiddleware is configured with sensible defaults for local development
- `https_only=False` allows HTTP local dev; set to `True` for production HTTPS
- Fallback credentials provide development authentication when PostgreSQL is down
- The code gracefully falls back from PostgreSQL to file-based auth

**What should be verified/done (not code changes):**
1. **For production deployment**: Ensure PostgreSQL is running and configured via environment variables (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`)
2. **For production deployment**: Set `SESSION_SECRET` via environment variable (not the fallback `secrets.token_hex(32)`)
3. **For production deployment**: Ensure `https_only=True` is set in SessionMiddleware when behind HTTPS
4. **Documentation**: Add a note that `fallback_creds.txt` is development-only and should not be used in production
5. **Documentation**: Add a note that production must use PostgreSQL as the authoritative user store

**No changes to `stcs_v1/` are needed or permitted.**

**No telescope hardware integration changes are needed.**

**Phase 1 is architecturally complete and ready for the verification stage.**

---
**Report generated:** Final Phase 1 Architecture Check