"""Pydantic request/response contracts (validation boundary)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class RecipientIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    course_name: Optional[str] = Field(default=None, max_length=255)
    metadata: Optional[dict] = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    course_name: str = Field(min_length=1, max_length=255)
    issuer: str = Field(min_length=1, max_length=255, default="Organization")
    recipients: list[RecipientIn] = Field(min_length=1)


class CertificateOut(BaseModel):
    id: str
    job_id: str
    recipient_name: str
    recipient_email: str
    course_name: str
    status: str
    error_message: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: str
    title: str
    course_name: str
    issuer: str
    status: str
    total: int
    succeeded: int
    failed: int
    progress_percent: float = 0.0
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class JobDetailOut(JobOut):
    certificates: list[CertificateOut] = []
    failures: list[CertificateOut] = []


def to_job_out(job) -> JobOut:
    done = job.succeeded + job.failed
    progress = round((done / job.total * 100.0) if job.total else 0.0, 2)
    return JobOut(
        id=job.id, title=job.title, course_name=job.course_name, issuer=job.issuer,
        status=job.status, total=job.total, succeeded=job.succeeded, failed=job.failed,
        progress_percent=progress, created_at=job.created_at, completed_at=job.completed_at,
    )
