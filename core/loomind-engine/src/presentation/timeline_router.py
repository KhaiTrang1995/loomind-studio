"""
Timeline Router — GET /api/timeline

Reverse-chronological supersession chain for a topic.
Requirements: 4.6
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.domain.models import TimelineEntry

router = APIRouter(prefix="/api", tags=["timeline"])


@router.get("/timeline", response_model=list[TimelineEntry])
async def timeline(req: Request, topic: str = Query(..., description="Topic to search for")) -> list[TimelineEntry]:
    """Get reverse-chronological timeline for a topic."""
    if not topic or not topic.strip():
        raise HTTPException(status_code=400, detail="topic required")

    graph_service = getattr(req.app.state, "graph_service", None)
    if graph_service is None:
        raise HTTPException(status_code=503, detail="Graph service not available")

    return await graph_service.timeline(topic)
