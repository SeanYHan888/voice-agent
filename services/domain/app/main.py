from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, engine, ensure_pgvector, get_db, SessionLocal
from .models import Provider, Slot, VisitType
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_pgvector()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="domain-service", lifespan=lifespan)


class ProviderOut(BaseModel):
    id: int
    name: str
    title: str

    model_config = {"from_attributes": True}


class SlotOut(BaseModel):
    id: int
    provider_id: int
    provider_name: str
    visit_type: str
    starts_at: datetime


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "domain"}


@app.get("/providers", response_model=list[ProviderOut])
def providers(db: Session = Depends(get_db)):
    return db.scalars(select(Provider).order_by(Provider.id)).all()


@app.get("/slots", response_model=list[SlotOut])
def slots(
    on: date | None = Query(default=None, description="Filter to a single day"),
    visit_type: str | None = None,
    provider_id: int | None = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    q = select(Slot).join(VisitType).where(Slot.status == "open").order_by(Slot.starts_at).limit(limit)
    if on is not None:
        q = q.where(Slot.starts_at >= datetime.combine(on, datetime.min.time()).astimezone())
        q = q.where(Slot.starts_at < datetime.combine(on, datetime.max.time()).astimezone())
    if visit_type is not None:
        q = q.where(VisitType.name == visit_type)
    if provider_id is not None:
        q = q.where(Slot.provider_id == provider_id)
    rows = db.scalars(q).all()
    return [
        SlotOut(
            id=s.id,
            provider_id=s.provider_id,
            provider_name=s.provider.name,
            visit_type=s.visit_type.name,
            starts_at=s.starts_at,
        )
        for s in rows
    ]
