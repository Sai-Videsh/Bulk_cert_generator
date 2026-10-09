"""Filesystem storage backend behind a tiny interface (swappable for S3/GCS)."""
import os
import zipfile
from pathlib import Path


class LocalStorage:
    def __init__(self, base_dir: str):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        d = self.base / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cert_path(self, job_id: str, cert_id: str) -> Path:
        return self.job_dir(job_id) / f"{cert_id}.pdf"

    def zip_job(self, job_id: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for pdf in sorted(self.job_dir(job_id).glob("*.pdf")):
                zf.write(pdf, arcname=pdf.name)
        return dest

    def file_size(self, path: str | Path) -> int:
        return os.path.getsize(path)
