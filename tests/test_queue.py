"""Queue tests: fallback seamless, adaptive bounds, dispatch works without Redis."""
from app.config import get_settings
from app.queue import InMemoryQueue, desired_workers, get_queue


def test_memory_fallback_when_no_url():
    get_settings().redis_url = ""
    q = get_queue()
    assert q.backend == "memory"


def test_memory_fallback_when_unreachable():
    get_settings().redis_url = "redis://127.0.0.1:6399/0"
    try:
        q = get_queue()
        assert q.backend == "memory"  # no server here; must not raise
    finally:
        get_settings().redis_url = ""


def test_memory_push_pop():
    q = InMemoryQueue()
    q.push("a")
    q.push("b")
    assert len(q) == 2
    assert q.pop_nowait() == "a"
    assert len(q) == 1


def test_desired_workers_bounds():
    cap = 8
    assert desired_workers(0, cap) == 1
    assert desired_workers(1, cap) <= 2  # tiny backlog: ~1 thread
    assert 1 < desired_workers(20, cap) <= cap
    assert desired_workers(10**6, cap) == cap


def test_dispatch_without_redis_completes_job():
    from app.services import jobs as J
    from tests.test_jobs import _payload, _wait_for_job, client

    J._reset_queue()
    get_settings().redis_url = ""
    try:
        r = client.post("/api/v1/jobs", json=_payload(names=("Q1",)))
        assert r.status_code == 202
        job = _wait_for_job(r.json()["id"])
        assert job["status"] == "completed"
    finally:
        J._reset_queue()
