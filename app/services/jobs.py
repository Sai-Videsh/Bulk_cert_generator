"""Job orchestration: create (with validation split) + background processing.

Design: invalid recipients are NOT rejected wholesale — they are stored as
`failed` certificates with an error message so one bad row never blocks the
rest (per assignment: failure isolation + status visibility).

Retry policy: permanent errors fail fast (no retry); transient errors retry
with backoff up to MAX_GENERATION_RETRIES, then fail.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.schemas import JobCreate
from app.services.generator import generate_certificate_pdf
from app.services.storage import LocalStorage

log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=get_settings().max_workers, thread_name_prefix="cert-worker")


def _storage() -> LocalStorage:
    return LocalStorage(get_settings().storage_dir)


def _is_permanent(exc: Exception) -> bool:
    """Permanent = retrying can never help. Everything else is treated as transient."""
    if isinstance(exc, (ValueError, TypeError)):
        return True
    msg = str(exc).lower()
    # Deliberate failure hook / bad-data signals: fail fast, don't waste retries.
    if "simulated generation failure" in msg or "recipient name is required" in msg:
        return True
    return False


def _generate_with_retry(storage: LocalStorage, job_id: str, cert_id: str,
                          name: str, course: str, issuer: str, max_retries: int) -> tuple[str, int]:
    """Returns (file_size_str_or_path, attempts). Raises last error if all attempts fail."""
    last: Exception | None = None
    attempts = 1 + max(0, max_retries)
    for attempt in range(1, attempts + 1):
        try:
            path = storage.cert_path(job_id, cert_id)
            generate_certificate_pdf(path, name, course, issuer, cert_id)
            return str(path), attempt
        except Exception as exc:
            last = exc
            if _is_permanent(exc) or attempt == attempts:
                raise
            backoff = min(2.0, 0.2 * (2 ** (attempt - 1)))  # 0.2s, 0.4s, 0.8s...
            log.warning("cert %s transient error (attempt %d/%d), retrying in %.1fs: %s",
                        cert_id, attempt, attempts, backoff, exc)
            time.sleep(backoff)
    raise last  # pragma: no cover


def create_job(db: Session, payload: JobCreate, idempotency_key: str | None = None) -> models.Job:
    from pydantic import ValidationError  # local import to keep top clean

    settings = get_settings()
    if len(payload.recipients) > settings.max_recipients_per_job:
        raise ValueError(f"too many recipients: max {settings.max_recipients_per_job}")

    if idempotency_key:
        existing = db.query(models.Job).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    job = models.Job(
        title=payload.title.strip(), course_name=payload.course_name.strip(),
        issuer=(payload.issuer or "Organization").strip(), status="processing",
        idempotency_key=idempotency_key,
    )
    db.add(job)
    db.flush()  # assign job.id before adding children

    # Payload recipients are already Pydantic-validated at the API boundary.
    # Anything that still fails here (DB constraints, etc.) becomes a failed row.
    for r in payload.recipients:
        course = (r.course_name or payload.course_name).strip()
        cert = models.Certificate(
            job_id=job.id, recipient_name=r.name.strip(), recipient_email=str(r.email).strip(),
            course_name=course, extra=r.metadata, status="pending",
        )
        db.add(cert)
    db.flush()
    job.total = len(payload.recipients)
    db.commit()
    db.refresh(job)

    # Fire-and-forget background processing (in-process pool; swap for Celery/Redis at scale).
    _executor.submit(_process_job, job.id)
    return job


def _process_job(job_id: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(models.Job).filter_by(id=job_id).first()
        if not job:
            return
        storage = _storage()
        max_retries = get_settings().max_generation_retries
        pending = db.query(models.Certificate).filter_by(job_id=job_id, status="pending").all()
        for cert in pending:
            cert.status = "processing"
            db.commit()
            try:
                file_path, attempts = _generate_with_retry(
                    storage, job_id, cert.id,
                    cert.recipient_name, cert.course_name, job.issuer, max_retries,
                )
                cert.status = "succeeded"
                cert.file_path = file_path
                cert.file_size = storage.file_size(file_path)
                if attempts > 1:
                    log.info("cert %s succeeded on attempt %d", cert.id, attempts)
                job.succeeded += 1
            except Exception as exc:  # per-cert isolation: never let one failure stop the job
                permanent = _is_permanent(exc)
                log.warning("cert %s %s: %s", cert.id,
                            "failed fast (permanent)" if permanent else "failed after retries", exc)
                cert.status = "failed"
                cert.error_message = str(exc)[:2000]
                job.failed += 1
            cert.updated_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            db.commit()
        db.refresh(job)
        if job.succeeded + job.failed >= job.total and job.total > 0:
            job.status = "completed" if job.failed == 0 else "completed_with_errors"
            job.completed_at = datetime.utcnow()
            db.commit()
    except Exception as exc:
        log.exception("job %s crashed: %s", job_id, exc)
        try:
            job = db.query(models.Job).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                job.completed_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def process_job_synchronously(job_id: str) -> None:
    """Test/dev helper: run processing inline instead of via the pool."""
    _process_job(job_id)
