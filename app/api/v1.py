"""REST API v1: bulk-first, async (202 Accepted), paginated, idempotent."""
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.database import get_db
from app.schemas import CertificateOut, JobCreate, JobDetailOut, JobOut, to_job_out
from app.services.jobs import create_job
from app.services.storage import LocalStorage

router = APIRouter()


def _storage() -> LocalStorage:
    return LocalStorage(get_settings().storage_dir)


@router.post("/jobs", response_model=JobOut, status_code=202)
def submit_job(
    payload: JobCreate,
    response: Response,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        job = create_job(db, payload, idempotency_key=idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=413 if "too many" in str(exc) else 422, detail=str(exc))
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return to_job_out(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
):
    limit = min(limit, get_settings().api_page_size_max)
    q = db.query(models.Job).order_by(models.Job.created_at.desc())
    if status:
        q = q.filter_by(status=status)
    return [to_job_out(j) for j in q.offset(offset).limit(limit).all()]


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    cert_limit: int = Query(default=100, ge=0, le=500),
    failures_limit: int = Query(default=100, ge=0, le=500),
):
    job = db.query(models.Job).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    out = to_job_out(job)
    # Bounded: never dump thousands of rows in one response. Full rows live on
    # GET /jobs/{id}/certificates (paginated). Small jobs are unaffected.
    base = db.query(models.Certificate).filter_by(job_id=job_id)
    total = base.count()
    failed_total = base.filter_by(status="failed").count()
    certs = base.order_by(models.Certificate.created_at).limit(cert_limit).all()
    failures = base.filter_by(status="failed").order_by(models.Certificate.created_at).limit(failures_limit).all() if failed_total else []
    return JobDetailOut(
        **out.model_dump(), certificates=certs, failures=failures,
        certificates_total=total, failures_total=failed_total,
        truncated=(total > len(certs) or failed_total > len(failures)),
    )


@router.get("/jobs/{job_id}/certificates", response_model=list[CertificateOut])
def list_job_certificates(
    job_id: str, db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1), offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
):
    limit = min(limit, get_settings().api_page_size_max)
    if not db.query(models.Job).filter_by(id=job_id).first():
        raise HTTPException(status_code=404, detail="job not found")
    q = db.query(models.Certificate).filter_by(job_id=job_id).order_by(models.Certificate.created_at)
    if status:
        q = q.filter_by(status=status)
    return q.offset(offset).limit(limit).all()


@router.get("/jobs/{job_id}/download")
def download_job_zip(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    storage = _storage()
    dest = Path(storage.base) / f"{job_id}.zip"
    # Wait briefly for in-flight background work in tests/local runs (bounded).
    for _ in range(40):
        ok = db.query(models.Certificate).filter_by(job_id=job_id, status="succeeded").count()
        if ok > 0 or (job.status in ("completed", "completed_with_errors", "failed")):
            break
        time.sleep(0.25)
        db.expire_all()
        job = db.query(models.Job).filter_by(id=job_id).first()
    storage.zip_job(job_id, dest)
    return FileResponse(str(dest), media_type="application/zip", filename=f"certificates-{job_id}.zip")


@router.get("/certificates/{cert_id}", response_model=CertificateOut)
def get_certificate(cert_id: str, db: Session = Depends(get_db)):
    cert = db.query(models.Certificate).filter_by(id=cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="certificate not found")
    return cert


@router.get("/certificates/{cert_id}/download")
def download_certificate(cert_id: str, db: Session = Depends(get_db)):
    cert = db.query(models.Certificate).filter_by(id=cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="certificate not found")
    if cert.status != "succeeded" or not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(status_code=409, detail=f"certificate not ready (status={cert.status})")
    # Confinement check: only serve files inside the configured storage dir.
    try:
        resolved = Path(cert.file_path).resolve()
        base = Path(get_settings().storage_dir).resolve()
        if base not in resolved.parents and resolved != base:
            raise HTTPException(status_code=500, detail="stored path outside storage dir")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="invalid stored path")
    return FileResponse(cert.file_path, media_type="application/pdf", filename=f"certificate-{cert_id}.pdf")


@router.get("/health")
def health(request: Request):
    return {"status": "ok", "app": get_settings().app_name}
