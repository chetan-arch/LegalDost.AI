"""In-process sliding-window rate limiter keyed by pseudonymous user key.

Single-process only. For multiple workers/instances, replace with a shared store (e.g. Redis).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.max_events <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            if len(self._events) > 100_000:  # bound memory
                self._events = {k: v for k, v in self._events.items() if v and now - v[-1] <= self.window}
            return True
