"""
Simple in-memory rate limiting for the STCS Web Application.

Provides per-endpoint rate limiting with time-based expiry.
Intended for authentication and expensive endpoints only.
Not for safety-critical endpoints (E-STOP, etc.).

Thread-safe for use with Starlette's async model via threading locks.
"""

import time
import threading
from collections import defaultdict
from typing import Dict, List, Tuple, Optional


class RateLimiter:
    """Simple token-bucket-like rate limiter with expiry."""

    def __init__(self, max_requests: int, window_s: float):
        """
        :param max_requests: maximum requests allowed within the window
        :param window_s: time window in seconds
        """
        self.max_requests = max_requests
        self.window_s = window_s
        self._lock = threading.Lock()
        # Maps endpoint key -> list of timestamps (recent request times)
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def _clean_window(self, key: str) -> List[float]:
        """Remove timestamps outside the current window for a given key."""
        now = time.time()
        timestamps = self._requests[key]
        recent = [t for t in timestamps if now - t < self.window_s]
        self._requests[key] = recent
        return recent

    def check(self, key: str) -> Tuple[bool, int]:
        """
        Check if a request is within rate limits.

        :param key: identifier for the rate limit (e.g., "ip:login")
        :return: (allowed, remaining_count) tuple
        """
        with self._lock:
            recent = self._clean_window(key)
            if len(recent) < self.max_requests:
                # Record this request
                recent.append(time.time())
                self._requests[key] = recent
                return True, self.max_requests - len(recent)
            else:
                return False, max(0, self.max_requests - len(recent))

    def reset(self, key: str):
        """Reset the counter for a given key (use for manual unlocking)."""
        with self._lock:
            self._requests[key] = []


# Pre-configured rate limiters for common use cases

# Login/auth: 5 attempts per minute
login_rate_limiter = RateLimiter(max_requests=5, window_s=60)

# Command requests: 20 per minute (but E-STOP should not be rate-limited)
command_rate_limiter = RateLimiter(max_requests=20, window_s=60)

# Export operations: 5 per minute
export_rate_limiter = RateLimiter(max_requests=5, window_s=60)


def is_rate_limited(key: str, limiter: RateLimiter) -> bool:
    """Check rate limit and return True if the request should be blocked."""
    allowed, _remaining = limiter.check(key)
    return not allowed