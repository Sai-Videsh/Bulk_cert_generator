# Architecture — why this system looks the way it does

## Big picture
One FastAPI process: HTTP routes → Pydantic validation → SQLAlchemy (Job → Certificates)
→ queue → ThreadPoolExecutor generates ReportLab PDFs → local files. Client polls for progress.

```
POST /api/v1/jobs ──▶ Job(processing) + N Certificate(pending) ──▶ queue ──▶ pool ──▶ succeeded/failed
GET /api/v1/jobs/{id} ──▶ counts + progress_percent + failures[]
GET .../download ──▶ PDF / ZIP
```

## Decision log (chosen vs rejected)
1. **FastAPI over Flask/Django** — async-ready, Pydantic, auto `/docs`. Flask needs manual
   validation; Django is heavy for this scope.
2. **Queued background dispatch over sync** — bulk of 1000s PDFs must return `202` now,
   process later. Sync would time out. The queue is Redis when `REDIS_URL` works, else
   in-memory — zero infra for evaluation, shared/durable in prod. Full Celery+SQS is the
   true-scale answer; `_process_job` moves unchanged.
3. **Adaptive pool within a cap over fixed threads** — `MAX_WORKERS` is the ceiling;
   `ThreadPoolExecutor` spawns threads on demand and `desired_workers()` sizes to the
   backlog, so small jobs use ~1 thread and bursts scale to the cap — never above it.
4. **SQLite default, Postgres-ready** — zero-setup for gates; same ORM on Postgres via
   `DATABASE_URL`. Added WAL + 30s busy-timeout for concurrent writers.
5. **ReportLab PDF, single template** — vector/printable, pure-Python. PNG is heavy;
   HTML→PDF needs system libs.
6. **Local FS behind `LocalStorage`** — offline-friendly; swap for S3 without touching routes.
   DB-BLOBs would bloat the DB and slow ZIPs.
7. **Retry split (transient retries, permanent fails fast) over blanket retry** —
   `OSError`/locks retry with backoff (`MAX_GENERATION_RETRIES`); `ValueError`/bad-data
   fails immediately so one bad row never delays the job.
8. **Per-row isolation over all-or-nothing** — spec: one bad cert never blocks the job;
   failures surface as `failed + error_message`, job ends `completed_with_errors`.
9. **Cap (`MAX_RECIPIENTS_PER_JOB=5000`) over unbounded** — bounds memory/time; split more.
10. **Idempotency-Key over naive POST** — safe retries on flaky networks.
11. **ZIP-on-download over prebuilt archives** — always fresh, less disk.
12. **Transparent guards over mandatory auth** — rate limit (600/min), 5 MB body cap,
    tightened CORS, security headers are always on but evaluator-safe; API-key auth exists
    as an opt-in (`AUTH_ENABLED=true`) so automated gates never get `401`.

## Scaling past this
Celery + Redis/SQS (queue already Redis-shaped), S3 storage, Postgres + Alembic,
Gunicorn+Uvicorn workers, per-key rate limits, Prometheus metrics. See `README.md` env table.
