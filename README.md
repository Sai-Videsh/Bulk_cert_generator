# Bulk Certificate Generator

Bulk-first REST API: one POST with N recipients → background PDF generation → poll progress → download PDFs/ZIP. Evaluator-safe guards on, auth opt-in off by default.

Docs: `docs/ARCHITECTURE.md` (decisions) · `docs/API_DESIGN.md` (endpoints + integration) · `docs/TESTING.md` (39 checks we ran).

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env   # optional; defaults work as-is
```

## Run
```bash
python -m app.cli serve --port 8000   # API + Swagger at /docs
streamlit run streamlit_app.py        # optional GUI (same API)
```

## Use
```bash
python -m app.cli create-job --file sample_job.json
python -m app.cli job-status <JOB_ID>
python -m app.cli download <JOB_ID> --out certs.zip
pytest -q   # 39 passed
```

## Config (.env)
| Key | Default | Meaning |
|---|---|---|
| `DATABASE_URL` / `STORAGE_DIR` | sqlite file / `./storage/certificates` | Postgres-ready via URL |
| `MAX_WORKERS` / `MAX_RECIPIENTS_PER_JOB` | 8 / 5000 | pool size / per-job cap |
| `RATE_LIMIT_PER_MINUTE` / `MAX_BODY_BYTES` | 600 / 5242880 | broad, evaluator-safe gates |
| `AUTH_ENABLED` / `API_keys` | false / empty | prod: `true` + keys, clients send `X-API-Key` |
| `CORS_ORIGINS` | `*` | prod: set explicit domains |

Behavior is identical with defaults (no keys needed); enabling auth/CORS changes only prod.
