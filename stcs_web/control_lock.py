"""
Control lock module — shared between observatory and command service.

Provides a single source of truth for telescope control lock ownership.
"""

import threading
import time
from typing import Dict, Any, Optional


# Module-level control lock state
_control_lock = {"owner": None, "acquired_at": 0.0, "ttl_s": 300.0}
_lock_guard = threading.Lock()


def control_lock_status() -> Dict[str, Any]:
    """Get current control lock status with TTL expiration check."""
    with _lock_guard:
        owner = _control_lock["owner"]
        if owner and time.time() - _control_lock["acquired_at"] > _control_lock["ttl_s"]:
            _control_lock["owner"] = None
            owner = None
        return {
            "owner": owner,
            "acquired_at": _control_lock["acquired_at"],
            "ttl_s": _control_lock["ttl_s"],
        }


def acquire_control_lock(username: str) -> Dict[str, Any]:
    """Acquire exclusive control lock for slew/calibration commands."""
    with _lock_guard:
        if _control_lock["owner"] and time.time() - _control_lock["acquired_at"] <= _control_lock["ttl_s"]:
            return {"ok": False, "owner": _control_lock["owner"]}
        _control_lock.update({"owner": username, "acquired_at": time.time()})
        return {"ok": True, "owner": username}


def release_control_lock(username: str, role: str = "scientist") -> Dict[str, Any]:
    """Release control lock. Admin can release anyone's lock."""
    with _lock_guard:
        if _control_lock["owner"] in (None, username) or role == "admin":
            _control_lock["owner"] = None
            return {"ok": True}
        return {"ok": False, "owner": _control_lock["owner"]}