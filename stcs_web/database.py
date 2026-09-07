import bcrypt
import os
import sys
from datetime import datetime, timezone

# Ensure bcrypt is available; fall back to SHA256+SALT if not
try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    import psycopg2
    from psycopg2 import sql


def get_db_connection():
    """Get a database connection using environment variables."""
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = int(os.environ.get("DB_PORT", "5432"))
    db_name = os.environ.get("DB_NAME", "stcs_observatory")
    db_user = os.environ.get("DB_USER", "stcs_user")
    db_password = os.environ.get("DB_PASSWORD", "")

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
    )
    return conn


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.
    
    Returns a bcrypt hash string that includes the cost factor, salt, and hash.
    Never store plaintext passwords.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify a password against a stored bcrypt hash.
    
    stored_hash format: bcrypt hash string (cost factor, salt, hash)
    """
    try:
        return bcrypt.checkpw(provided_password.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False


def init_users_table():
    """Initialize the users table in PostgreSQL.
    
    Creates the table if it doesn't exist.
    This is additive - never drops existing data.
    Gracefully handles missing or unavailable PostgreSQL.
    """
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(128) UNIQUE NOT NULL,
                        password_hash VARCHAR(256) NOT NULL,
                        role VARCHAR(32) NOT NULL DEFAULT 'scientist',
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                    )
                """)
                
                # Create index for faster lookups
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)
                """)
                
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)
                """)
                
                conn.commit()
        finally:
            conn.close()
    except (psycopg2.OperationalError, psycopg2.InterfaceError, Exception):
        # Database not available - this is not fatal for Phase 1
        # The web app can still function with session-based auth
        # PostgreSQL will be initialized when available
        pass


def create_user(username: str, password: str, role: str = "scientist") -> dict:
    """Create a new user in the database.
    
    Returns user dict with id, username, role.
    Raises ValueError if username already exists.
    """
    hashed = hash_password(password)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id, username, role",
                    (username, hashed, role),
                )
                row = cur.fetchone()
                conn.commit()
                return {"id": row[0], "username": row[1], "role": row[2]}
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                raise ValueError(f"Username '{username}' already exists")
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    """Get a user by username. Returns user dict or None."""
    # Try PostgreSQL first
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, password_hash, role, is_active, created_at, updated_at FROM users WHERE username = %s",
                    (username,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "id": row[0],
                    "username": row[1],
                    "password_hash": row[2],
                    "role": row[3],
                    "is_active": row[4],
                    "created_at": row[5],
                    "updated_at": row[6],
                }
        finally:
            conn.close()
    except (psycopg2.OperationalError, psycopg2.InterfaceError, Exception):
        # Database not available - fall back to file-based credentials
        pass
    
    # Fall back to file-based development credentials.
    # WHY positional ids: the file has no numeric id column, so each line's
    # index is its stable fallback id. Every user gets a DISTINCT id —
    # otherwise a scientist session (id 0) would resolve to the admin record.
    for entry in _read_fallback_users():
        if entry["username"] == username:
            return {
                "id": entry["id"],
                "username": entry["username"],
                "password_hash": entry["password_hash"],
                "role": entry["role"],
                "is_active": True,
                "created_at": None,
                "updated_at": None,
            }
    
    return None


def _read_fallback_users():
    """Parse fallback_creds.txt into [{id, username, password_hash, role}]."""
    fallback_file = os.path.join(os.path.dirname(__file__), "fallback_creds.txt")
    entries = []
    try:
        with open(fallback_file, "r") as f:
            for idx, line in enumerate(f):
                parts = line.strip().split(":")
                if len(parts) == 3:
                    stored_user, stored_hash, stored_role = parts
                    entries.append({
                        "id": idx,
                        "username": stored_user,
                        "password_hash": stored_hash,
                        "role": stored_role,
                    })
    except FileNotFoundError:
        pass
    return entries


def get_user_by_id(user_id: int) -> dict | None:
    """Get a user by ID. Returns user dict or None."""
    # Try PostgreSQL first
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, password_hash, role, is_active, created_at, updated_at FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "id": row[0],
                    "username": row[1],
                    "password_hash": row[2],
                    "role": row[3],
                    "is_active": row[4],
                    "created_at": row[5],
                    "updated_at": row[6],
                }
        finally:
            conn.close()
    except (psycopg2.OperationalError, psycopg2.InterfaceError, Exception):
        # Database not available - fall back to file-based credentials
        pass
    
    # Fall back to file-based development credentials (positional ids).
    for entry in _read_fallback_users():
        if entry["id"] == user_id:
            return {
                "id": entry["id"],
                "username": entry["username"],
                "password_hash": entry["password_hash"],
                "role": entry["role"],
                "is_active": True,
                "created_at": None,
                "updated_at": None,
            }
    
    return None


def update_user_activity(user_id: int):
    """Update the user's last_active timestamp (best-effort).

    WHY swallowed errors: activity tracking must never break an
    authenticated request when PostgreSQL is unavailable (the file-based
    development fallback has no updated_at column to write).
    """
    try:
        conn = get_db_connection()
    except Exception:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET updated_at = NOW() WHERE id = %s",
                (user_id,),
            )
            conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass