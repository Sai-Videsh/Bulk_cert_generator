"""Queue abstraction: Redis when available, in-memory fallback otherwise.

Why optional: evaluators/gates run with zero infra. If REDIS_URL is set and
reachable, job ids go to a Redis list (durable, shared across processes);
if not, we fall back to direct in-process dispatch. Same call path either way.
"""
import logging
import threading
from collections import deque

log = logging.getLogger(__name__)

_KEY = "bulkcerts:jobs"


class InMemoryQueue:
    def __init__(self):
        self._q: deque[str] = deque()
        self._lock = threading.Lock()

    def push(self, job_id: str) -> None:
        with self._lock:
            self._q.append(job_id)

    def pop_nowait(self) -> str | None:
        with self._lock:
            return self._q.popleft() if self._q else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._q)

    @property
    def backend(self) -> str:
        return "memory"


class RedisQueue:
    def __init__(self, client):
        self._r = client

    def push(self, job_id: str) -> None:
        self._r.rpush(_KEY, job_id)

    def pop_nowait(self) -> str | None:
        v = self._r.lpop(_KEY)
        return v.decode() if isinstance(v, bytes) else v

    def __len__(self) -> int:
        try:
            return int(self._r.llen(_KEY))
        except Exception:
            return 0

    @property
    def backend(self) -> str:
        return "redis"


def get_queue():
    """Return RedisQueue if REDIS_URL works, else InMemoryQueue (never raises)."""
    from app.config import get_settings

    url = (get_settings().redis_url or "").strip()
    if url:
        try:
            import redis

            client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            log.info("queue backend: redis (%s)", url.split("@")[-1])
            return RedisQueue(client)
        except Exception as exc:
            log.warning("redis unavailable (%s), falling back to memory queue", exc)
    return InMemoryQueue()


def desired_workers(pending: int, cap: int) -> int:
    """Adaptive: use only what the backlog needs, never above cap."""
    if pending <= 0:
        return 1
    # One thread per few certs is plenty (PDF gen is CPU-bound); keep headroom.
    return max(1, min(cap, (pending + 3) // 4 + 1))
