# Testing — what we ran (42 tests, all green)

Run: `pytest -q` → `42 passed` (`test_jobs.py`: 6 core · `test_extended.py`: 33 gates · `test_retry.py`: 3).

## Core (test_jobs.py)
- Create → `202` + `Location`, `total` correct.
- Validation → bad email + blank name → `422`.
- Generation + progress → 3/3 `completed`, `progress_percent == 100`.
- Single failure → `FAIL Guy` job → `completed_with_errors 2/1`, `failures[0]` carries message.
- Retrieval → single PDF starts `%PDF`, ZIP returns `application/zip`.
- Idempotency → same `Idempotency-Key` → same job id.

## Gates/guards (test_extended.py, 33)
- Validation: empty list, missing title/course, 4 bad-email shapes, blank/giant name,
  wrong-type recipients, metadata dict accepted (10).
- Guards: body cap `413` at 10 bytes; rate limit `429` at 3/min then recover; probes exempt;
  `nosniff/DENY/no-referrer` headers; `/ready ok`; CORS preflight; 404s; 20-request burst passes (9).
- Auth: disabled allows keyless (default); enabled rejects missing/wrong (`401`), accepts correct,
  probes stay open (5).
- Jobs/retrieval: `Location` header, pagination, limit clamp ≤100, progress, `?status=failed`
  filter, PDF bytes, ZIP type, idempotent resubmit (8).

## Retry policy (test_retry.py, 3)
- Classification: `ValueError/TypeError`/simulated-failure → permanent (fail fast);
  `OSError`/lock errors → transient (retry).
- Transient recovers: flaky-once generator succeeds on attempt 2.
- Permanent doesn't retry: always-bad generator called exactly once.

## Live break-probes (ad-hoc, all correct)
Empty/oversize-5001 (`422/413`), missing job/cert (`404`), traversal path (`404`),
duplicate emails accepted as separate certs, mixed FAIL job → `completed_with_errors`.
No `500`s observed.
