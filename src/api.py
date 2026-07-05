"""
HTTP service wrapping the defense-news classifier.

Exposes the existing `classify()` function (one LLM call -> structured output)
as a small FastAPI app so the model can be called over HTTP instead of only as
a batch script. Deliberately thin: validation, error handling, and health
checks live here; the classification logic stays in classify.py.

Run locally:
    uvicorn api:app --app-dir src --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Flat import works when uvicorn is started with `--app-dir src` (local + Docker).
from classify import CATEGORIES, DOMAINS, classify, make_client

logger = logging.getLogger(__name__)


# The Anthropic client is created once at startup and reused across requests.
# Re-creating it per request would waste connections; a single client is fine to
# share. Building it in the lifespan handler means startup fails loudly if the
# API key is missing, rather than failing on the first request.
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the shared Anthropic client once at startup and expose it via ``app.state``."""
    app.state.client = make_client()
    yield


app = FastAPI(
    title="Defense News Classifier",
    description="Classify a defense-news snippet into a category and operational domain.",
    version="2.0.0",
    lifespan=lifespan,
)


class ClassifyRequest(BaseModel):
    """Request body for ``POST /classify``."""

    # Bound the input: empty text is meaningless, and a hard cap protects us from
    # someone pasting a whole document (and the token bill that comes with it).
    text: str = Field(
        ...,
        min_length=1,
        max_length=10_000,
        description="The defense-news article snippet to classify.",
    )


class ClassifyResponse(BaseModel):
    """Response body for ``POST /classify``."""

    category: str = Field(..., description=f"One of: {', '.join(CATEGORIES)}")
    operational_domain: str = Field(..., description=f"One of: {', '.join(DOMAINS)}")


@app.get("/health")
def health() -> dict:
    """Liveness probe. Does not call the LLM, so it stays cheap and fast."""
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
def classify_article(req: ClassifyRequest) -> ClassifyResponse:
    """Classify a defense-news snippet into a category and operational domain.

    Args:
        req: Request body containing the article ``text`` (1–10 000 chars).

    Returns:
        ClassifyResponse with ``category`` and ``operational_domain`` fields.

    Raises:
        HTTPException: 422 if text is blank after stripping whitespace;
            502 if the upstream LLM call fails.
    """
    text = req.text.strip()
    if not text:
        # min_length catches "", but a whitespace-only string slips through.
        raise HTTPException(status_code=422, detail="text must not be blank.")
    try:
        result = classify(app.state.client, text)
    except Exception as exc:
        # The upstream LLM call failed (network, rate limit, API error). Surface
        # a 502 rather than a 500: the fault is an upstream dependency, not us.
        # Log the real cause server-side for debugging, but return a generic
        # detail to the caller — the raw exception text can carry internal detail
        # (model name, request fragments) that shouldn't leak over the wire.
        logger.exception("Classification failed for a request")
        raise HTTPException(
            status_code=502, detail="Classification failed due to an upstream error."
        ) from exc
    return ClassifyResponse(**result)
