# API design guide

Base: `http://HOST:8000`, prefix `/api/v1`. Docs: `/docs`. Health: `/health /live /ready`.

## Endpoints
| Method + path | In | Out |
|---|---|---|
| `POST /api/v1/jobs` | `{title, course_name, issuer, recipients[{name, email, course_name?, metadata?}]}` + optional `Idempotency-Key` | `202 {id, status, total, ...}` + `Location` |
| `GET /api/v1/jobs?limit&offset&status` | pagination/filter | `[JobOut]` |
| `GET /api/v1/jobs/{id}` | — | job + `progress_percent` + `certificates[]` + `failures[]` |
| `GET /api/v1/jobs/{id}/certificates?status&limit&offset` | `status=succeeded\|failed` | `[CertificateOut]` |
| `GET /api/v1/certificates/{id}` | — | metadata |
| `GET /api/v1/certificates/{id}/download` | — | `application/pdf` (`409` if not ready) |
| `GET /api/v1/jobs/{id}/download` | — | `application/zip` |

## Lifecycles
- Job: `processing → completed` (all ok) · `completed_with_errors` (partial) · `failed` (crash only).
- Cert: `pending → processing → succeeded | failed`.

## Status codes
`202` accepted · `401` only when `AUTH_ENABLED=true` and key missing/wrong · `404` unknown id ·
`409` PDF not ready · `413` body/recipients over cap · `422` validation · `429` rate limit + `Retry-After`.

## Integration pattern (any language)
1. `POST` job (send `Idempotency-Key: <your-batch-id>`, and `X-API-Key` only if prod enabled it).
2. Poll `GET /jobs/{id}` every 2s until `completed*`.
3. `GET .../certificates?status=failed` for errors; download ZIP / single PDFs.
4. On `429`, wait `Retry-After` and resume; on `413/422`, fix payload (never blind-retry).

## Why this shape
Bulk-first (one POST, N certs), async (`202` + poll avoids timeouts), idempotent (safe retries),
paginated (bounded responses), file downloads as binary (no base64 bloat), probes open (load
balancers work with or without auth).
