from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine, ensure_pgvector, SessionLocal
from .routers import admin, calls, patients, scheduling, verification
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_pgvector()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="domain-service", lifespan=lifespan)

app.include_router(scheduling.router)
app.include_router(patients.router)
app.include_router(calls.router)
app.include_router(verification.router)
app.include_router(admin.router)


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "domain"}
