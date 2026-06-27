"""
Gates Router — GET /api/gates

System readiness and observability endpoint.
Reports per-subsystem status, tier counts, and queue depths.

Requirements: 10.1, 10.2
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from src.domain.evolution.tiers import TIER_COLLECTION, KnowledgeTier
from src.domain.models import GatesStatus

router = APIRouter(prefix="/api", tags=["gates"])


@router.get("/gates", response_model=GatesStatus)
async def gates(req: Request) -> GatesStatus:
    """Report readiness of all engine subsystems."""
    service = req.app.state.service
    worker = getattr(req.app.state, "worker", None)

    # Qdrant connectivity
    qdrant_ok = service.qdrant.is_healthy()

    # Embedder availability
    embedder_loaded = service.embedder.is_loaded

    # LLM availability
    llm_available = False
    try:
        llm_available = await service.llm.is_available()
    except Exception:
        pass

    # Worker states
    judge_status = "stopped"
    evolve_status = "stopped"
    judge_depth = 0
    if worker:
        judge_status = worker.judge_worker_status
        evolve_status = worker.evolve_cron_status
        judge_depth = worker.queue_depth

    # Tier counts
    tiers = {}
    for tier in KnowledgeTier:
        col = TIER_COLLECTION.get(tier)
        if col:
            try:
                tiers[tier.value] = service.qdrant.count(col)
            except Exception:
                tiers[tier.value] = 0

    return GatesStatus(
        qdrant_ok=qdrant_ok,
        embedder_loaded=embedder_loaded,
        llm_available=llm_available,
        judge_worker=judge_status,
        evolve_cron=evolve_status,
        tiers=tiers,
        queue_depth={"judge": judge_depth, "extract": 0},
    )
