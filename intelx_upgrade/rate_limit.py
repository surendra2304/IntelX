from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from threading import RLock
import time

@dataclass(frozen=True, slots=True)
class LimitDecision:
    allowed: bool
    remaining: int
    retry_after: float = 0.0

class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float):
        if limit <= 0 or window_seconds <= 0: raise ValueError("invalid limiter")
        self.limit, self.window = limit, window_seconds
        self._lock = RLock()
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str) -> LimitDecision:
        now = time.monotonic()
        with self._lock:
            q = self._events.setdefault(key, deque())
            cutoff = now - self.window
            while q and q[0] <= cutoff: q.popleft()
            if len(q) >= self.limit:
                return LimitDecision(False, 0, max(0.0, self.window-(now-q[0])))
            q.append(now)
            return LimitDecision(True, self.limit-len(q))
