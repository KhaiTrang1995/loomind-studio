"""
Evolve Router — POST /api/evolve

Triggers an evolution cycle. Idempotent — multiple calls without
new observations produce the same result.

Requirements: 7.6
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.domain.models import EvolutionReport

router = APIRouter(prefix="/api", tags=["evolve"])


class EvolutionRequest(BaseModel):
    """Optional parameters for an evolution cycle."""

    batch_size: int = Field(default=100, ge=1, le=1000, description="Max observations to consume per cycle")
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Min confidence for T2→T1 promotion")


@router.post("/evolve", response_model=EvolutionReport)
async def evolve(body: EvolutionRequest = EvolutionRequest(), req: Request = None) -> EvolutionReport:
    """Trigger an evolution cycle (promote/demote/abstract/prune/consume observations)."""
    evolution_service = getattr(req.app.state, "evolution_service", None)
    if evolution_service is None:
        raise HTTPException(status_code=503, detail="Evolution service not available")

    return await evolution_service.run_cycle(batch_size=body.batch_size)
