"""
Observation history + audit foundation — Phase 2.

WHY: Scientist observation privacy must be enforced by the backend and the
database queries, never by frontend hiding. Admin sees their own records
plus explicitly-authorized scientist records; scientists see only their own.

Schema is additive only (CREATE TABLE IF NOT EXISTS). No destructive
migrations. All queries are parameterized.

Tables:
  observations      — one row per observation with owner_username
  observation_files — file metadata linked to an observation
  audit_events      — login/logout/access/export/command-attempt events
"""

from datetime import datetime, timezone

import psycopg2

from .database import get_db_connection


def init_obs_tables():
    """Create observation/audit tables if missing. Returns True if DB ready."""
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"Observation store unavailable (no PostgreSQL): {e}")
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id SERIAL PRIMARY KEY,
                    owner_username VARCHAR(128) NOT NULL,
                    target VARCHAR(256) NOT NULL DEFAULT '',
                    ra_deg DOUBLE PRECISION,
                    dec_deg DOUBLE PRECISION,
                    start_time TIMESTAMP WITH TIME ZONE,
                    end_time TIMESTAMP WITH TIME ZONE,
                    duration_s DOUBLE PRECISION,
                    status VARCHAR(64) NOT NULL DEFAULT 'completed',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_owner ON observations(owner_username)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_target ON observations(target)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_start ON observations(start_time)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS observation_files (
                    id SERIAL PRIMARY KEY,
                    observation_id INTEGER NOT NULL REFERENCES observations(id),
                    filename VARCHAR(512) NOT NULL,
                    kind VARCHAR(64) NOT NULL DEFAULT 'data',
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id SERIAL PRIMARY KEY,
                    actor_username VARCHAR(128) NOT NULL,
                    action VARCHAR(128) NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_username)"
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"Observation store init failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _visible_to_clause(username: str, role: str):
    """Return (WHERE fragment, params) enforcing ownership privacy."""
    if role == "admin":
        return "", []
    return "owner_username = %s", [username]


def list_observations(username, role, q="", status="", date_from="",
                      date_to="", limit=25, offset=0):
    """List observations visible to the caller with filters + pagination."""
    where = []
    params = []
    owner_clause, owner_params = _visible_to_clause(username, role)
    if owner_clause:
        where.append(owner_clause)
        params.extend(owner_params)
    if q:
        where.append("(target ILIKE %s OR notes ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if status:
        where.append("status = %s")
        params.append(status)
    if date_from:
        where.append("start_time >= %s")
        params.append(date_from)
    if date_to:
        where.append("start_time <= %s")
        params.append(date_to)
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM observations {sql_where}", params)
            total = cur.fetchone()[0]
            cur.execute(
                f"""SELECT id, owner_username, target, ra_deg, dec_deg,
                           start_time, end_time, duration_s, status
                    FROM observations {sql_where}
                    ORDER BY start_time DESC NULLS LAST, id DESC
                    LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    items = [
        {"id": r[0], "owner": r[1], "target": r[2], "ra_deg": r[3],
         "dec_deg": r[4], "start": str(r[5]) if r[5] else None,
         "end": str(r[6]) if r[6] else None, "duration_s": r[7],
         "status": r[8]}
        for r in rows
    ]
    return {"total": total, "items": items}


def get_observation(obs_id, username, role):
    """Fetch one observation only if the caller is authorized to see it."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, owner_username, target, ra_deg, dec_deg,
                          start_time, end_time, duration_s, status, notes
                   FROM observations WHERE id = %s""",
                (obs_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if role != "admin" and row[1] != username:
                return None  # privacy: scientist B cannot read scientist A
            cur.execute(
                "SELECT id, filename, kind FROM observation_files "
                "WHERE observation_id = %s ORDER BY id",
                (obs_id,),
            )
            files = [{"id": f[0], "filename": f[1], "kind": f[2]}
                     for f in cur.fetchall()]
    finally:
        conn.close()
    return {"id": row[0], "owner": row[1], "target": row[2],
            "ra_deg": row[3], "dec_deg": row[4],
            "start": str(row[5]) if row[5] else None,
            "end": str(row[6]) if row[6] else None,
            "duration_s": row[7], "status": row[8], "notes": row[9],
            "files": files}


def record_audit(actor_username, action, detail=""):
    """Best-effort audit log; never raises (observatory must keep running)."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_events (actor_username, action, detail)"
                    " VALUES (%s, %s, %s)",
                    (actor_username, action, detail[:2000]),
                )
                conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def utcnow():
    return datetime.now(timezone.utc)


def db_available():
    """Probe PostgreSQL without side effects."""
    try:
        conn = get_db_connection()
        conn.close()
        return True
    except Exception:
        return False
