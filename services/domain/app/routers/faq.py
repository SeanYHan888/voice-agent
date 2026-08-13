from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..faq import search

router = APIRouter(prefix="/faq", tags=["faq"])


class FaqQuery(BaseModel):
    query: str
    k: int = Field(default=3, ge=1, le=5)


@router.post("/search")
def faq_search(body: FaqQuery, db: Session = Depends(get_db)):
    """Clinic information lookup. Unauthenticated by design — Maya answers these
    before any Verification."""
    return {"results": search(db, body.query, body.k)}
