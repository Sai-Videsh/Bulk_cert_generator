"""FastAPI application factory with health probes, CORS, and request logging."""
import logging
import time

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_router
from app.auth import require_api_key
from app.config import get_settings
from app.database import init_db
from app.middleware import GuardMiddleware

logging.basicConfig(level=get_settings().log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-API-Key"],
        allow_credentials=False,
    )
    app.add_middleware(
        GuardMiddleware,
        max_body_bytes=settings.max_body_bytes,
        per_minute=settings.rate_limit_per_minute,
    )

    @app.middleware("http")
    async def log_requests(request, call_next):
        start = time.time()
        resp = await call_next(request)
        log.info("%s %s -> %s (%.1fms)", request.method, request.url.path, resp.status_code, (time.time() - start) * 1000)
        return resp

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/live")
    def live():
        return {"status": "alive"}

    @app.get("/ready")
    def ready(response: Response):
        try:
            from sqlalchemy import text

            from app.database import engine

            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "ready"}
        except Exception as exc:
            response.status_code = 503
            return {"status": "not-ready", "error": str(exc)}

    app.include_router(v1_router, prefix=settings.api_prefix, dependencies=[Depends(require_api_key)])
    return app


app = create_app()
