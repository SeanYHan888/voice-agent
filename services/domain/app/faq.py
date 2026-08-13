"""FAQ retrieval over the clinic corpus.

The corpus is small and static, so embeddings are generated once at startup and stored
in pgvector. Retrieval is a cosine-distance search; a result that is not close enough
returns nothing at all, which is what lets Maya admit she doesn't know.
"""
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import FaqChunk

log = logging.getLogger(__name__)

EMBED_MODEL = "text-embedding-3-small"
EMBED_URL = "https://api.openai.com/v1/embeddings"
# Beyond this cosine distance a chunk is treated as unrelated to the question.
RELEVANCE_CUTOFF = 0.75


def _embed(texts: list[str]) -> list[list[float]]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    response = httpx.post(
        EMBED_URL,
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={"model": EMBED_MODEL, "input": texts},
        timeout=30,
    )
    response.raise_for_status()
    return [item["embedding"] for item in response.json()["data"]]


def ensure_corpus_embedded(db: Session) -> None:
    pending = db.scalars(select(FaqChunk).where(FaqChunk.embedding.is_(None))).all()
    if not pending:
        return
    if not settings.openai_api_key:
        log.warning("Skipping FAQ embedding: no OpenAI key configured")
        return
    try:
        vectors = _embed([f"{c.title}. {c.text}" for c in pending])
    except Exception:
        log.exception("FAQ embedding failed; retrieval will be unavailable")
        return
    for chunk, vector in zip(pending, vectors):
        chunk.embedding = vector
    db.commit()
    log.info("Embedded %d FAQ chunks", len(pending))


def search(db: Session, query: str, k: int = 3) -> list[dict]:
    try:
        query_vector = _embed([query])[0]
    except Exception:
        log.exception("FAQ query embedding failed")
        return []

    distance = FaqChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = db.execute(
        select(FaqChunk, distance)
        .where(FaqChunk.embedding.is_not(None))
        .order_by(distance)
        .limit(k)
    ).all()

    return [
        {"title": chunk.title, "text": chunk.text, "distance": round(float(dist), 4)}
        for chunk, dist in rows
        if dist <= RELEVANCE_CUTOFF
    ]
