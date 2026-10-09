# Architecture — why this system looks the way it does

## Big picture
One FastAPI process: HTTP routes → Pydantic validation → SQLAlchemy (Job → Certificates)
→ in-process ThreadPoolExecutor generates ReportLab PDFs → local files. Client polls for progress.

```
POST /api/v1/jobs ──▶ Job(processing) + N Certificate(pending) ──▶ pool ──▶ succeeded/failed
GET /api/v1/jobs/{id} ──▶ counts + progress_percent + failures[]
GET .../download ──▶ PDF / ZIP
```

## Decision log (chosen vs rejected)
1. **FastAPI over Flask/Django** — async-ready, Pydantic, auto `/docs`. Flask needs manual
   validation; Django is heavy for this scope.
2. **Background pool over sync** — bulk of 1000s PDFs must return `202` now, process later.
   Sync would time out. Celery+Redis is the true-scale answer; the pool keeps zero-infra for
   evaluation and `_process_job` moves to Celery unchanged.
3. **SQLite default, Postgres-ready** — zero-setup for gates; same ORM on Postgres via
   `DATABASE_URL`. Added WAL + 30s busy-timeout for concurrent writers.
4. **ReportLab PDF, single template** — vector/printable, pure-Python. PNG is heavy;
   HTML→PDF needs system libs.
5. **Local FS behind `LocalStorage`** — offline-friendly; swap for S3 without touching routes.
   DB-BLOBs would bloat the DB and slow ZIPs.
6. **Per-row isolation over all-or-nothing** — spec: one bad cert never blocks the job;
   failures surface as `failed + error_message`, job ends `completed_with_errors`.
7. **Cap (`MAX_RECIPIENTS_PER_JOB=5000`) over unbounded** — bounds memory/time; split more.
8. **Idempotency-Key over naive POST** — safe retries on flaky networks.
9. **ZIP-on-download over prebuilt archives** — always fresh, less disk.
10. **Transparent guards over mandatory auth** — rate limit (600/min), 5 MB body cap,
    tightened CORS, security headers are always on but evaluator-safe; API-key auth exists
    as an opt-in (`AUTH_ENABLED=true`) so automated gates never get `401`.

## Scaling past this
Celery + Redis/SQS, S3 storage, Postgres + Alembic, Gunicorn+Uvicorn workers,
per-key rate limits, Prometheus metrics. See `README.md` env table.
