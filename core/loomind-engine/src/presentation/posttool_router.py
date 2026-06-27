"""
PostTool Router — POST /api/posttool

Accepts closed-loop feedback after tool use, validates trace_id,
enqueues for judge evaluation, returns 202 Accepted.

Requirements: 3.1, 3.6
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from src.domain.models import PostToolAck, PostToolRequest
from src.infrastructure.background_worker import BackpressureError

router = APIRouter(prefix="/api", tags=["posttool"])


@router.post("/posttool", response_model=PostToolAck, status_code=202)
async def posttool(body: PostToolRequest, req: Request) -> PostToolAck:
    """Enqueue a posttool feedback item for judge evaluation.

    Validates required fields and trace_id, returns 202 Accepted.
    """
    # Validate required fields
    if not body.trace_id or not body.trace_id.strip():
        raise HTTPException(status_code=400, detail="Missing or empty trace_id")
    if not body.suggestion_ids:
        raise HTTPException(status_code=400, detail="Missing suggestion_ids")
    if not body.action_taken or not body.action_taken.strip():
        raise HTTPException(status_code=400, detail="Missing action_taken")

    worker = getattr(req.app.state, "worker", None)
    if worker is None:
        raise HTTPException(status_code=503, detail="Judge worker not available")

    # Enqueue each suggestion for judging
    from src.domain.models import JudgeItem

    job_ids = []
    for sid in body.suggestion_ids:
        item = JudgeItem(
            trace_id=body.trace_id,
            suggestion_id=sid,
            action_taken=body.action_taken,
            transcript_snippet=body.transcript_snippet,
        )
        try:
            job_id = await worker.enqueue_judge(item)
            job_ids.append(job_id)
        except BackpressureError:
            raise HTTPException(status_code=503, detail="Judge queue full; try again later")

    return PostToolAck(
        accepted=True,
        queued_at=datetime.now(timezone.utc),
        job_id=job_ids[0] if job_ids else "none",
    )
