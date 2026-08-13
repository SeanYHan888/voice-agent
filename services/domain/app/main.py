import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .logging_middleware import RequestLogMiddleware

from .db import Base, engine, ensure_pgvector, SessionLocal
from .faq import ensure_corpus_embedded
from .routers import admin, analytics, calls, faq, patients, scheduling, verification
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_pgvector()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        ensure_corpus_embedded(db)
    yield


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="domain-service", lifespan=lifespan)
app.add_middleware(RequestLogMiddleware, service="domain")

app.include_router(scheduling.router)
app.include_router(patients.router)
app.include_router(faq.router)
app.include_router(calls.router)
app.include_router(verification.router)
app.include_router(admin.router)
app.include_router(analytics.router)


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "domain"}
