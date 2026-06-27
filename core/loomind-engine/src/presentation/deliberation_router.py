"""
Deliberation Router — multi-CLI deliberation endpoints.

POST /api/deliberate                          — CLI starts a deliberation
GET  /api/deliberations                       — list all deliberations
GET  /api/deliberations/{id}                  — get single deliberation
PATCH /api/deliberations/{id}/resolve         — human resolves HITL deliberation

Phase 12 — Multi-CLI Deliberation.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.domain.models import (
    ConsultRequest,
    ConsultResponse,
    Deliberation,
    HITLResolveRequest,
)

router = APIRouter(prefix="/api", tags=["deliberation"])


@router.post("/deliberate", response_model=ConsultResponse, status_code=202)
async def start_deliberation(body: ConsultRequest, req: Request) -> ConsultResponse:
    """CLI posts here when it needs peer consultation. Returns immediately — rounds run async."""
    svc = getattr(req.app.state, "deliberation_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="DeliberationService not available")
    return await svc.start(body)


@router.get("/deliberations", response_model=list[Deliberation])
async def list_deliberations(req: Request) -> list[Deliberation]:
    """Return all deliberations, newest first."""
    svc = getattr(req.app.state, "deliberation_service", None)
    if svc is None:
        return []
    return svc.get_all()


@router.get("/deliberations/{deliberation_id}", response_model=Deliberation)
async def get_deliberation(deliberation_id: str, req: Request) -> Deliberation:
    svc = getattr(req.app.state, "deliberation_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="DeliberationService not available")
    d = svc.get(deliberation_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"Deliberation {deliberation_id!r} not found")
    return d


@router.patch("/deliberations/{deliberation_id}/resolve", response_model=Deliberation)
async def resolve_hitl(deliberation_id: str, body: HITLResolveRequest, req: Request) -> Deliberation:
    """Human approves or rejects a HITL-pending deliberation."""
    svc = getattr(req.app.state, "deliberation_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="DeliberationService not available")
    d = await svc.resolve_hitl(deliberation_id, body)
    if d is None:
        raise HTTPException(status_code=404, detail=f"Deliberation {deliberation_id!r} not found")
    return d
