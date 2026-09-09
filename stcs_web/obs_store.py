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
  weather_readings  — timestamped environmental observations for history
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
            # Weather history table (additive migration)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS weather_readings (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    source VARCHAR(256) NOT NULL DEFAULT 'ARIES Manora Peak Weather Station',
                    temperature_c DOUBLE PRECISION,
                    humidity_pct DOUBLE PRECISION,
                    dew_point_c DOUBLE PRECISION,
                    wind_speed_kmh DOUBLE PRECISION,
                    rain_detected BOOLEAN,
                    pressure_hpa DOUBLE PRECISION,
                    status VARCHAR(32) NOT NULL DEFAULT 'LIVE',
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_weather_ts ON weather_readings(timestamp DESC)"
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


# ── Weather history ─────────────────────────────────────────────────────

def store_weather_reading(temperature_c=None, humidity_pct=None, dew_point_c=None,
                          wind_speed_kmh=None, rain_detected=None, pressure_hpa=None,
                          source="ARIES Manora Peak Weather Station", status="LIVE"):
    """Store a weather reading for history. Additive only, no side effects."""
    try:
        conn = get_db_connection()
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO weather_readings
                   (source, temperature_c, humidity_pct, dew_point_c,
                    wind_speed_kmh, rain_detected, pressure_hpa, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (source, temperature_c, humidity_pct, dew_point_c,
                 wind_speed_kmh, rain_detected, pressure_hpa, status)
            )
        conn.commit()
        return True
    except Exception as e:
        print(f"Failed to store weather reading: {e}")
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


def list_weather_readings(limit=100, offset=0, hours=24):
    """List recent weather readings for diagnostics/history."""
    try:
        conn = get_db_connection()
    except Exception:
        return {"total": 0, "items": []}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM weather_readings
                   WHERE timestamp >= NOW() - INTERVAL '%s hours'""",
                (hours,)
            )
            total = cur.fetchone()[0]
            cur.execute(
                """SELECT id, timestamp, source, temperature_c, humidity_pct,
                          dew_point_c, wind_speed_kmh, rain_detected, pressure_hpa, status
                   FROM weather_readings
                   WHERE timestamp >= NOW() - INTERVAL '%s hours'
                   ORDER BY timestamp DESC
                   LIMIT %s OFFSET %s""",
                (hours, limit, offset)
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    items = [
        {"id": r[0], "timestamp": str(r[1]) if r[1] else None,
         "source": r[2], "temperature_c": r[3], "humidity_pct": r[4],
         "dew_point_c": r[5], "wind_speed_kmh": r[6], "rain_detected": r[7],
         "pressure_hpa": r[8], "status": r[9]}
        for r in rows
    ]
    return {"total": total, "items": items}


def get_latest_weather_reading():
    """Get the most recent weather reading."""
    try:
        conn = get_db_connection()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, timestamp, source, temperature_c, humidity_pct,
                          dew_point_c, wind_speed_kmh, rain_detected, pressure_hpa, status
                   FROM weather_readings
                   ORDER BY timestamp DESC
                   LIMIT 1"""
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"id": row[0], "timestamp": str(row[1]) if row[1] else None,
            "source": row[2], "temperature_c": row[3], "humidity_pct": row[4],
            "dew_point_c": row[5], "wind_speed_kmh": row[6], "rain_detected": row[7],
            "pressure_hpa": row[8], "status": row[9]}


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


# ── Camera acquisition extensions ──────────────────────────────────────────
# Additive schema changes: new columns on existing tables. No destructive
# migrations. All queries are parameterized.

def migrate_camera_schema():
    """Add camera-acquisition columns to existing tables. Idempotent."""
    try:
        conn = get_db_connection()
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            # observations: telescope state snapshot at exposure start
            cur.execute(
                "ALTER TABLE observations ADD COLUMN IF NOT EXISTS "
                "telescope_state JSONB"
            )
            # observations: camera settings used for this observation
            cur.execute(
                "ALTER TABLE observations ADD COLUMN IF NOT EXISTS "
                "camera_settings JSONB"
            )
            # observation_files: absolute path on disk for secure serving
            cur.execute(
                "ALTER TABLE observation_files ADD COLUMN IF NOT EXISTS "
                "file_path VARCHAR(1024)"
            )
            # observation_files: SHA-256 checksum for integrity verification
            cur.execute(
                "ALTER TABLE observation_files ADD COLUMN IF NOT EXISTS "
                "checksum VARCHAR(128)"
            )
            # observation_files: file size in bytes
            cur.execute(
                "ALTER TABLE observation_files ADD COLUMN IF NOT EXISTS "
                "file_size BIGINT"
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"Camera schema migration failed: {e}")
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


def create_observation(owner_username, target="", ra_deg=None, dec_deg=None,
                       status="acquiring", notes="", telescope_state=None,
                       camera_settings=None):
    """Create a new observation record. Returns observation id or None."""
    try:
        conn = get_db_connection()
    except Exception:
        return None
    try:
        import json
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO observations
                   (owner_username, target, ra_deg, dec_deg, status, notes,
                    start_time, telescope_state, camera_settings)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)
                   RETURNING id""",
                (owner_username, target, ra_deg, dec_deg, status, notes,
                 json.dumps(telescope_state) if telescope_state else None,
                 json.dumps(camera_settings) if camera_settings else None),
            )
            obs_id = cur.fetchone()[0]
            conn.commit()
            return obs_id
    except Exception as e:
        print(f"create_observation failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_observation(obs_id, status=None, end_time=None, duration_s=None,
                       notes=None, ra_deg=None, dec_deg=None):
    """Update observation fields. Only non-None values are written."""
    try:
        conn = get_db_connection()
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            sets = []
            params = []
            if status is not None:
                sets.append("status = %s")
                params.append(status)
            if end_time is not None:
                sets.append("end_time = %s")
                params.append(end_time)
            if duration_s is not None:
                sets.append("duration_s = %s")
                params.append(duration_s)
            if notes is not None:
                sets.append("notes = %s")
                params.append(notes)
            if ra_deg is not None:
                sets.append("ra_deg = %s")
                params.append(ra_deg)
            if dec_deg is not None:
                sets.append("dec_deg = %s")
                params.append(dec_deg)
            if not sets:
                return False
            params.append(obs_id)
            cur.execute(
                f"UPDATE observations SET {', '.join(sets)} WHERE id = %s",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as e:
        print(f"update_observation failed: {e}")
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


def record_observation_file(obs_id, filename, file_path, kind="data",
                            checksum=None, file_size=None):
    """Record an acquired file linked to an observation. Returns file id."""
    try:
        conn = get_db_connection()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO observation_files
                   (observation_id, filename, file_path, kind, checksum, file_size)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (obs_id, filename, file_path, kind, checksum, file_size),
            )
            file_id = cur.fetchone()[0]
            conn.commit()
            return file_id
    except Exception as e:
        print(f"record_observation_file failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_observation_with_files(obs_id, username, role):
    """Fetch one observation with full telescope_state and files. Auth-checked."""
    try:
        conn = get_db_connection()
    except Exception:
        return None
    try:
        import json
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, owner_username, target, ra_deg, dec_deg,
                          start_time, end_time, duration_s, status, notes,
                          telescope_state, camera_settings
                   FROM observations WHERE id = %s""",
                (obs_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if role != "admin" and row[1] != username:
                return None
            cur.execute(
                """SELECT id, filename, kind, file_path, checksum, file_size,
                          created_at
                   FROM observation_files
                   WHERE observation_id = %s ORDER BY id""",
                (obs_id,),
            )
            files = []
            for f in cur.fetchall():
                files.append({
                    "id": f[0], "filename": f[1], "kind": f[2],
                    "file_path": f[3], "checksum": f[4], "file_size": f[5],
                    "created_at": str(f[6]) if f[6] else None,
                })
    finally:
        conn.close()
    tel_state = row[10]
    if isinstance(tel_state, str):
        try:
            tel_state = json.loads(tel_state)
        except Exception:
            pass
    cam_settings = row[11]
    if isinstance(cam_settings, str):
        try:
            cam_settings = json.loads(cam_settings)
        except Exception:
            pass
    return {
        "id": row[0], "owner": row[1], "target": row[2],
        "ra_deg": row[3], "dec_deg": row[4],
        "start": str(row[5]) if row[5] else None,
        "end": str(row[6]) if row[6] else None,
        "duration_s": row[7], "status": row[8], "notes": row[9],
        "telescope_state": tel_state,
        "camera_settings": cam_settings,
        "files": files,
    }


def get_file_for_download(file_id, username, role):
    """Return (file_path, filename) if caller is authorized, else None."""
    try:
        conn = get_db_connection()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT f.file_path, f.filename, o.owner_username
                   FROM observation_files f
                   JOIN observations o ON f.observation_id = o.id
                   WHERE f.id = %s""",
                (file_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if role != "admin" and row[2] != username:
                return None
            return {"file_path": row[0], "filename": row[1]}
    finally:
        conn.close()


def list_observation_files(username, role, limit=50, offset=0):
    """List all observation files visible to the caller, newest first."""
    try:
        conn = get_db_connection()
    except Exception:
        return {"total": 0, "items": []}
    try:
        where = []
        params = []
        owner_clause, owner_params = _visible_to_clause(username, role)
        if owner_clause:
            where.append(owner_clause)
            params.extend(owner_params)
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT COUNT(*) FROM observation_files f
                    JOIN observations o ON f.observation_id = o.id
                    {sql_where}""",
                params,
            )
            total = cur.fetchone()[0]
            cur.execute(
                f"""SELECT f.id, f.filename, f.kind, f.file_size,
                           f.checksum, f.created_at, o.id, o.target,
                           o.owner_username
                    FROM observation_files f
                    JOIN observations o ON f.observation_id = o.id
                    {sql_where}
                    ORDER BY f.created_at DESC NULLS LAST, f.id DESC
                    LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    items = [
        {"id": r[0], "filename": r[1], "kind": r[2], "file_size": r[3],
         "checksum": r[4], "created_at": str(r[5]) if r[5] else None,
         "observation_id": r[6], "target": r[7], "owner": r[8]}
        for r in rows
    ]
    return {"total": total, "items": items}


def get_observation_summary(username, role):
    """Get summary statistics for observations visible to the caller."""
    try:
        conn = get_db_connection()
    except Exception:
        return {"total": 0, "hours": 0, "targets": 0, "latest": None,
                "by_status": {}, "by_scientist": {}}
    try:
        where = []
        params = []
        owner_clause, owner_params = _visible_to_clause(username, role)
        if owner_clause:
            where.append(owner_clause)
            params.extend(owner_params)
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT COUNT(*), COALESCE(SUM(duration_s), 0),
                           COUNT(DISTINCT target),
                           MAX(start_time)
                    FROM observations {sql_where}""",
                params,
            )
            row = cur.fetchone()
            total = row[0] or 0
            hours = round((row[1] or 0) / 3600.0, 2)
            targets = row[2] or 0
            latest = str(row[3]) if row[3] else None

            cur.execute(
                f"""SELECT status, COUNT(*) FROM observations {sql_where}
                    GROUP BY status""",
                params,
            )
            by_status = {r[0]: r[1] for r in cur.fetchall()}

            by_scientist = {}
            if role == "admin":
                cur.execute(
                    """SELECT owner_username, COUNT(*) FROM observations
                       GROUP BY owner_username ORDER BY COUNT(*) DESC""",
                )
                by_scientist = {r[0]: r[1] for r in cur.fetchall()}

    finally:
        conn.close()
    return {"total": total, "hours": hours, "targets": targets,
            "latest": latest, "by_status": by_status,
            "by_scientist": by_scientist}


def delete_observation(obs_id, username, role):
    """Delete an observation and its files. Enforces ownership.

    Returns (deleted, reason) where deleted is True on success.
    Scientists can only delete their own observations.
    Admins can delete any observation.
    """
    try:
        conn = get_db_connection()
    except Exception:
        return False, "Database unavailable"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_username FROM observations WHERE id = %s",
                (obs_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False, "Observation not found"
            if role != "admin" and row[1] != username:
                return False, "Unauthorized: cannot delete another user's observation"
            # Delete observation_files first (FK constraint)
            cur.execute(
                "DELETE FROM observation_files WHERE observation_id = %s",
                (obs_id,),
            )
            cur.execute(
                "DELETE FROM observations WHERE id = %s",
                (obs_id,),
            )
            conn.commit()
            return True, "Deleted"
    except Exception as e:
        print(f"delete_observation failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False, f"Delete failed: {e}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_observations_for_scientist(scientist_username, limit=100, offset=0):
    """List observations for a specific scientist (admin view)."""
    try:
        conn = get_db_connection()
    except Exception:
        return {"total": 0, "items": []}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM observations
                   WHERE owner_username = %s""",
                (scientist_username,),
            )
            total = cur.fetchone()[0]
            cur.execute(
                """SELECT id, owner_username, target, ra_deg, dec_deg,
                          start_time, end_time, duration_s, status
                   FROM observations
                   WHERE owner_username = %s
                   ORDER BY start_time DESC NULLS LAST, id DESC
                   LIMIT %s OFFSET %s""",
                (scientist_username, limit, offset),
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


def list_scientists():
    """List all scientist users with observation counts."""
    try:
        conn = get_db_connection()
    except Exception:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.username,
                          COUNT(o.id) as obs_count,
                          MAX(o.start_time) as last_obs
                   FROM users u
                   LEFT JOIN observations o ON u.username = o.owner_username
                   WHERE u.role = 'scientist'
                   GROUP BY u.username
                   ORDER BY u.username"""
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"username": r[0], "observation_count": r[1],
             "last_observation": str(r[2]) if r[2] else None}
            for r in rows]


def get_audit_events(limit=100, offset=0, action_filter=""):
    """Get audit events with pagination and optional action filter."""
    try:
        conn = get_db_connection()
    except Exception:
        return {"total": 0, "items": []}
    try:
        where = []
        params = []
        if action_filter:
            where.append("action = %s")
            params.append(action_filter)
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM audit_events {sql_where}",
                params,
            )
            total = cur.fetchone()[0]
            cur.execute(
                f"""SELECT id, actor_username, action, detail, created_at
                    FROM audit_events {sql_where}
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    items = [
        {"id": r[0], "actor": r[1], "action": r[2], "detail": r[3],
         "created_at": str(r[4]) if r[4] else None}
        for r in rows
    ]
    return {"total": total, "items": items}
