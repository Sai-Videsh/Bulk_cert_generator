"""Optional API-key auth — OFF by default so gates/evaluators pass seamlessly.

Prod: set AUTH_ENABLED=true and API_KEYS=secret1,secret2, then clients send
X-API-Key: <one of the keys> on every /api/v1 call. Health probes stay open.
"""
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from app.config import get_settings

_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Depends(_scheme)) -> None:
    s = get_settings()
    if not s.auth_enabled:
        return
    allowed = {k.strip() for k in s.api_keys.split(",") if k.strip()}
    if not key or key not in allowed:
        raise HTTPException(status_code=401, detail="missing or invalid API key")
