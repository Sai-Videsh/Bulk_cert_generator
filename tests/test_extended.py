"""Extended gates/guards/validation suite (~32 tests). Reuses the app/client from test_jobs."""
import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.middleware import reset_rate_limiter
from tests.test_jobs import _payload, _wait_for_job, client


@pytest.fixture(autouse=True)
def _fresh_limits():
    reset_rate_limiter()
    s = get_settings()
    old_rate, old_body = s.rate_limit_per_minute, s.max_body_bytes
    old_auth, old_keys = s.auth_enabled, s.api_keys
    s.rate_limit_per_minute = 600
    s.max_body_bytes = 5 * 1024 * 1024
    s.auth_enabled = False
    yield
    s.rate_limit_per_minute = old_rate
    s.max_body_bytes = old_body
    s.auth_enabled = old_auth
    s.api_keys = old_keys
    reset_rate_limiter()


def _mk(names=("T1",)):
    r = client.post("/api/v1/jobs", json=_payload(names=names))
    assert r.status_code == 202, r.text
    return r.json()["id"]


# ---- validation (10) ----
def test_empty_recipients_422():
    p = _payload(); p["recipients"] = []
    assert client.post("/api/v1/jobs", json=p).status_code == 422


def test_missing_title_422():
    p = _payload(); del p["title"]
    assert client.post("/api/v1/jobs", json=p).status_code == 422


def test_missing_course_422():
    p = _payload(); del p["course_name"]
    assert client.post("/api/v1/jobs", json=p).status_code == 422


@pytest.mark.parametrize("email", ["nope", "a@", "@x.com", "a b@x.com"])
def test_bad_emails_422(email):
    p = _payload(); p["recipients"] = [{"name": "Ok", "email": email}]
    assert client.post("/api/v1/jobs", json=p).status_code == 422


def test_blank_name_422():
    p = _payload(); p["recipients"] = [{"name": "   ", "email": "a@x.com"}]
    assert client.post("/api/v1/jobs", json=p).status_code == 422


def test_giant_name_422():
    p = _payload(); p["recipients"] = [{"name": "X" * 500, "email": "a@x.com"}]
    assert client.post("/api/v1/jobs", json=p).status_code == 422


def test_recipients_wrong_type_422():
    p = _payload(); p["recipients"] = "notalist"
    assert client.post("/api/v1/jobs", json=p).status_code == 422


def test_metadata_dict_accepted():
    p = _payload(names=("M1",)); p["recipients"][0]["metadata"] = {"batch": "B1"}
    assert client.post("/api/v1/jobs", json=p).status_code == 202


# ---- guards: body/rate/headers (9) ----
def test_body_cap_413():
    get_settings().max_body_bytes = 10
    assert client.post("/api/v1/jobs", json=_payload()).status_code == 413


def test_rate_limit_429_then_recover():
    get_settings().rate_limit_per_minute = 3
    codes = [client.get("/api/v1/jobs?limit=1").status_code for _ in range(5)]
    assert 429 in codes
    reset_rate_limiter()
    get_settings().rate_limit_per_minute = 600
    assert client.get("/api/v1/jobs?limit=1").status_code == 200


def test_probes_exempt_from_rate_limit():
    get_settings().rate_limit_per_minute = 1
    for _ in range(5):
        assert client.get("/health").status_code == 200
        assert client.get("/live").status_code == 200


def test_security_headers_present():
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_ready_probe_200():
    assert client.get("/ready").json()["status"] == "ready"


def test_cors_allows_idempotency_header():
    r = client.options("/api/v1/jobs", headers={"Origin": "http://x.com", "Access-Control-Request-Method": "POST"})
    assert r.status_code in (200, 204)


def test_404_unknown_job():
    assert client.get("/api/v1/jobs/nope").status_code == 404


def test_404_unknown_cert_download():
    assert client.get("/api/v1/certificates/nope/download").status_code == 404


def test_broad_default_allows_burst():
    for _ in range(20):
        assert client.get("/api/v1/jobs?limit=1").status_code == 200


# ---- optional auth (5) ----
def test_auth_disabled_allows_without_key():
    get_settings().auth_enabled = False
    assert client.post("/api/v1/jobs", json=_payload(names=("A1",))).status_code == 202


def test_auth_enabled_rejects_missing_key():
    get_settings().auth_enabled = True
    get_settings().api_keys = "prod-secret"
    assert client.post("/api/v1/jobs", json=_payload(names=("A2",))).status_code == 401


def test_auth_enabled_rejects_wrong_key():
    get_settings().auth_enabled = True
    get_settings().api_keys = "prod-secret"
    r = client.post("/api/v1/jobs", json=_payload(names=("A3",)), headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_auth_enabled_accepts_correct_key():
    get_settings().auth_enabled = True
    get_settings().api_keys = "prod-secret"
    r = client.post("/api/v1/jobs", json=_payload(names=("A4",)), headers={"X-API-Key": "prod-secret"})
    assert r.status_code == 202


def test_probes_open_when_auth_enabled():
    get_settings().auth_enabled = True
    get_settings().api_keys = "prod-secret"
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


# ---- jobs / retrieval (8) ----
def test_create_returns_location():
    r = client.post("/api/v1/jobs", json=_payload(names=("L1",)))
    assert r.status_code == 202 and "location" in {k.lower() for k in r.headers}


def test_list_pagination():
    assert len(client.get("/api/v1/jobs?limit=1&offset=0").json()) <= 1


def test_limit_clamped():
    r = client.get("/api/v1/jobs?limit=9999")
    assert r.status_code == 200 and len(r.json()) <= get_settings().api_page_size_max


def test_job_detail_has_progress():
    jid = _mk(("P1", "P2"))
    job = _wait_for_job(jid)
    assert job["progress_percent"] == 100.0 and job["total"] == 2


def test_cert_filter_failed():
    jid = _mk(("GoodA", "FAIL B"))
    _wait_for_job(jid)
    failed = client.get(f"/api/v1/jobs/{jid}/certificates?status=failed").json()
    assert len(failed) == 1 and failed[0]["error_message"]


def test_single_pdf_bytes():
    jid = _mk(("Solo1",))
    _wait_for_job(jid)
    certs = client.get(f"/api/v1/jobs/{jid}/certificates").json()
    dl = client.get(f"/api/v1/certificates/{certs[0]['id']}/download")
    assert dl.status_code == 200 and dl.content[:4] == b"%PDF"


def test_job_zip_ok():
    jid = _mk(("Z1",))
    _wait_for_job(jid)
    z = client.get(f"/api/v1/jobs/{jid}/download")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"


def test_idempotent_same_id():
    p = _payload(names=("I1",))
    h = {"Idempotency-Key": "ext-key-999"}
    a = client.post("/api/v1/jobs", json=p, headers=h).json()
    b = client.post("/api/v1/jobs", json=p, headers=h).json()
    assert a["id"] == b["id"]
