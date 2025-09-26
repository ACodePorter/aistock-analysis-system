import threading
import time
from collections import defaultdict
from typing import Dict


class NewsMetrics:
    """Lightweight in-process counters for news pipeline.

    Note: These counters reset on process restart.
    """
    _lock = threading.Lock()
    _counters: Dict[str, int] = defaultdict(int)
    _gauges: Dict[str, float] = defaultdict(float)
    _started_at = time.time()

    @classmethod
    def inc(cls, key: str, delta: int = 1) -> None:
        with cls._lock:
            cls._counters[key] += delta

    @classmethod
    def add_gauge(cls, key: str, value: float) -> None:
        with cls._lock:
            cls._gauges[key] = value

    @classmethod
    def snapshot(cls) -> dict:
        with cls._lock:
            uptime = time.time() - cls._started_at
            return {
                "uptime_sec": int(uptime),
                "counters": dict(cls._counters),
                "gauges": dict(cls._gauges),
            }

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._counters.clear()
            cls._gauges.clear()
            cls._started_at = time.time()
