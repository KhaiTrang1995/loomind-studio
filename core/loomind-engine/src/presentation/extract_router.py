"""
Extract Router — POST /api/extract

Accepts session transcripts, extracts lessons via LLM, stores in T3.
Requirements: 8.4, 8.5, 8.6
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from src.domain.models import ExtractResult

router = APIRouter(prefix="/api", tags=["extract"])

MAX_TRANSCRIPT_LENGTH = 100_000


@router.post("/extract", response_model=ExtractResult, status_code=201)
async def extract(req: Request, body: dict) -> ExtractResult:
    """Extract lessons from a session transcript."""
    transcript = body.get("transcript", "")
    session_id = body.get("session_id", "unknown")
    max_lessons = body.get("max_lessons", 10)

    # Validation
    if not transcript or not transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript is empty")
    if len(transcript) > MAX_TRANSCRIPT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Transcript exceeds maximum length of {MAX_TRANSCRIPT_LENGTH} characters",
        )

    # Rate limiting
    rate_limiter = getattr(req.app.state, "rate_limiter", None)
    if rate_limiter:
        token = req.headers.get("Authorization", "anonymous")
        allowed, retry_after = rate_limiter.check(token)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

    extraction_service = getattr(req.app.state, "extraction_service", None)
    if extraction_service is None:
        raise HTTPException(status_code=503, detail="Extraction service not available")

    result = await extraction_service.extract(
        transcript=transcript,
        session_id=session_id,
        max_lessons=min(max_lessons, 10),
    )
    return result
