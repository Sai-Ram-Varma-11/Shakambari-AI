import asyncio
import json
import logging
import sys
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import settings
from .db import Base, SessionLocal, engine
from .food_migrations import apply_food_policy_migrations
from . import models  # noqa: F401
from .routers import (
    admin,
    alerts,
    auth,
    bookings,
    kitchen,
    menu,
    menu_opt,
    predict,
    surplus,
    sustainability,
    users,
    vision,
    waste,
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


handler = logging.StreamHandler(sys.stdout)
if settings.app_env == "production":
    handler.setFormatter(JsonFormatter())
else:
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

logging.root.handlers = [handler]
logging.root.setLevel(logging.INFO)
log = logging.getLogger("shakambari")


async def _tick():
    from .models import Institution
    from .services.alerts_engine import generate

    while True:
        try:
            db = SessionLocal()
            for (i,) in db.query(Institution.id):
                generate(db, i)
            db.close()
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(900)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-run table creation and migrations on startup
    Base.metadata.create_all(engine)
    apply_food_policy_migrations(engine)

    # Seed synthetic demo data if empty and SEED_DEMO_ON_EMPTY=true
    if settings.seed_demo_on_empty:
        try:
            db = SessionLocal()
            from .models import Institution

            if db.query(Institution).count() == 0:
                log.info("Database is empty and SEED_DEMO_ON_EMPTY=true. Initializing demo seed...")
                from . import seed

                seed.run(n_students=60, days_back=30, reset=False, quiet=True)
            db.close()
        except Exception as e:
            log.warning("Demo auto-seed check skipped: %s", e)

    task = asyncio.create_task(_tick()) if settings.scheduler_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="Shakambari AI API",
    version=settings.app_version,
    description="Think Smart. Serve Right. Waste Less. Closed-loop dining-hall food waste reduction and surplus redistribution.",
    lifespan=lifespan,
)

# Tightened CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-request-id", "x-institution-id", "x-device-token"],
)


@app.middleware("http")
async def security_and_request_id(request: Request, call_next):
    # Request-ID Tracking
    req_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = req_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id

    # Security Headers
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), geolocation=(), microphone=()")

    # Content Security Policy suited for Vite build
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss: https:; "
        "font-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    response.headers.setdefault("Content-Security-Policy", csp)

    if settings.app_env == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")

    return response


@app.exception_handler(RequestValidationError)
async def validation(request: Request, exc):
    msgs = [f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "; ".join(msgs) or "Invalid request"})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", "unknown")
    log.exception("Unhandled error on %s [request_id=%s]: %s", request.url.path, req_id, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on the server", "request_id": req_id},
    )


for r in (auth, users, menu, bookings, predict, kitchen, waste, surplus, menu_opt, vision, alerts, sustainability, admin):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health():
    db_status = "ok"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "service": "shakambari-ai",
        "version": settings.app_version,
        "database": db_status,
    }
