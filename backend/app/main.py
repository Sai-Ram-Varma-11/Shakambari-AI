import asyncio, logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import Base, SessionLocal, engine
from .food_migrations import apply_food_policy_migrations
from . import models  # noqa: F401
from .routers import admin, alerts, auth, bookings, kitchen, menu, menu_opt, predict, surplus, sustainability, users, vision, waste

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("platesense")


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
async def lifespan(app):
    Base.metadata.create_all(engine)
    apply_food_policy_migrations(engine)
    task = asyncio.create_task(_tick()) if settings.scheduler_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="PlateSense AI API", version="1.0.0", description="Think Smart. Serve Right. Waste Less.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def headers(request: Request, call_next):
    r = await call_next(request)
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("X-Frame-Options", "DENY")
    r.headers.setdefault("Referrer-Policy", "no-referrer")
    return r


@app.exception_handler(RequestValidationError)
async def validation(request, exc):
    msgs = [f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "; ".join(msgs) or "Invalid request"})


@app.exception_handler(Exception)
async def unhandled(request, exc):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server"})


for r in (auth, users, menu, bookings, predict, kitchen, waste, surplus, menu_opt, vision, alerts, sustainability, admin):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "platesense-ai"}
