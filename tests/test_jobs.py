"""Covers the assignment's required test areas:
creating a job, validation, generation, status/progress,
individual failure isolation, retrieval.
"""
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as dbmod
from app.config import get_settings
from app.database import Base, get_db
from app.main import create_app

TEST_DB = "./test_bulk_certs.db"
Path(TEST_DB).unlink(missing_ok=True)
engine = create_engine(f"sqlite:///{TEST_DB}", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)
# Point the background worker at the TEST database (it opens its own session).
dbmod.SessionLocal = TestingSession
dbmod.engine = engine


def _override():
    d = TestingSession()
    try:
        yield d
    finally:
        d.close()


app = create_app()
app.dependency_overrides[get_db] = _override
client = TestClient(app)

# Isolate file output per test run
get_settings().storage_dir = "./storage/test-certificates"


def _payload(names=("Alice", "Bob")):
    return {
        "title": "Test Workshop",
        "course_name": "Python 101",
        "issuer": "Test Org",
        "recipients": [{"name": n, "email": f"{n.lower().replace(' ', '_')}@example.com"} for n in names],
    }


def _wait_for_job(job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200
        job = r.json()
        if job["status"] in ("completed", "completed_with_errors", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish in time")


def test_create_job_returns_202_and_location():
    r = client.post("/api/v1/jobs", json=_payload())
    assert r.status_code == 202, r.text
    assert "Location" in r.headers
    assert r.json()["total"] == 2


def test_input_validation_rejects_bad_email_and_blank_name():
    bad = _payload()
    bad["recipients"] = [{"name": "  ", "email": "not-an-email"}]
    r = client.post("/api/v1/jobs", json=bad)
    assert r.status_code == 422  # FastAPI/Pydantic boundary rejects the whole request


def test_certificate_generation_and_status_progress():
    r = client.post("/api/v1/jobs", json=_payload(names=("Carol", "Dave", "Erin")))
    job_id = r.json()["id"]
    job = _wait_for_job(job_id)
    assert job["status"] == "completed"
    assert job["succeeded"] == 3 and job["failed"] == 0
    assert job["progress_percent"] == 100.0


def test_individual_failure_does_not_block_others():
    r = client.post("/api/v1/jobs", json=_payload(names=("Good One", "FAIL Guy", "Good Two")))
    job_id = r.json()["id"]
    job = _wait_for_job(job_id)
    assert job["status"] == "completed_with_errors"
    assert job["succeeded"] == 2 and job["failed"] == 1
    detail = client.get(f"/api/v1/jobs/{job_id}").json()
    assert len(detail["failures"]) == 1
    assert "simulated generation failure" in detail["failures"][0]["error_message"]


def test_retrieve_single_certificate_and_job_zip():
    r = client.post("/api/v1/jobs", json=_payload(names=("Zara",)))
    job_id = r.json()["id"]
    _wait_for_job(job_id)
    certs = client.get(f"/api/v1/jobs/{job_id}/certificates").json()
    assert len(certs) == 1
    dl = client.get(f"/api/v1/certificates/{certs[0]['id']}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/pdf"
    assert dl.content[:4] == b"%PDF"
    z = client.get(f"/api/v1/jobs/{job_id}/download")
    assert z.status_code == 200
    assert z.headers["content-type"] == "application/zip"


def test_idempotent_resubmit_returns_same_job():
    payload = _payload(names=("Idem Person",))
    h = {"Idempotency-Key": "test-key-123"}
    a = client.post("/api/v1/jobs", json=payload, headers=h).json()
    b = client.post("/api/v1/jobs", json=payload, headers=h).json()
    assert a["id"] == b["id"]
