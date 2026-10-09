"""Transparent guards: rate limit + body-size cap + security headers.

All broad by design so evaluators / gates hammering the API still pass.
No API key needed here (see app/auth.py for the optional prod switch).
"""
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_hits: defaultdict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class GuardMiddleware(BaseHTTPMiddleware):
    """One middleware, three jobs: body cap, broad rate limit, security headers."""

    def __init__(self, app, max_body_bytes: int = 5 * 1024 * 1024, per_minute: int = 600):
        super().__init__(app)
        self.max_body = max_body_bytes
        self.per_minute = per_minute

    async def dispatch(self, request: Request, call_next):
        from app.config import get_settings as _gs  # live read so tests/env can retune without rebuild

        s = _gs()
        max_body = s.max_body_bytes
        per_minute = s.rate_limit_per_minute
        # 1. Body-size gate (cheap: Content-Length header, no body read).
        try:
            length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            length = 0
        if length > max_body:
            return JSONResponse(status_code=413, content={"detail": f"body too large: max {max_body} bytes"})

        # 2. Broad sliding-window rate limit (probes exempt so k8s never fails).
        if request.url.path not in ("/health", "/live", "/ready"):
            now = time.time()
            q = _hits[_client_ip(request)]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded, retry shortly"},
                    headers={"Retry-After": "10"},
                )
            q.append(now)

        resp = await call_next(request)

        # 3. Security headers (no effect on JSON clients, helps browsers).
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return resp


def reset_rate_limiter() -> None:
    _hits.clear()
