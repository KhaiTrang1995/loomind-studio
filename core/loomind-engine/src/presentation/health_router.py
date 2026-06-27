"""
Health Router — /health, /ready, /api/stats endpoints.
"""

import time

from fastapi import APIRouter, Request

from src.domain.models import EngineStats, HealthStatus

router = APIRouter(tags=["health"])

_start_time = time.monotonic()


@router.get("/health", response_model=HealthStatus)
async def health(req: Request) -> HealthStatus:
    """Liveness probe — is the engine process running?"""
    service = req.app.state.service
    return HealthStatus(
        status="ok",
        engine="running",
        qdrant=service.qdrant.is_healthy(),
        embedder_loaded=service.embedder.is_loaded,
        llm_available=False,  # Checked lazily
        uptime_seconds=time.monotonic() - _start_time,
        version="0.3.0",
    )


@router.get("/ready")
async def ready(req: Request) -> dict:
    """Readiness probe — are all dependencies ready?"""
    service = req.app.state.service
    qdrant_ok = service.qdrant.is_healthy()
    embedder_ok = service.embedder.is_loaded

    if qdrant_ok and embedder_ok:
        return {"ready": True}
    return {"ready": False, "qdrant": qdrant_ok, "embedder": embedder_ok}


@router.get("/api/stats", response_model=EngineStats)
async def stats(req: Request) -> EngineStats:
    """Engine statistics."""
    service = req.app.state.service
    total = service.qdrant.count(service.collection)
    return EngineStats(
        total_experiences=total,
        total_queries=service.total_queries,
        avg_latency_ms=service.avg_latency_ms,
        cache_hit_rate=0.0,
        queries_today=service.total_queries,
    )
