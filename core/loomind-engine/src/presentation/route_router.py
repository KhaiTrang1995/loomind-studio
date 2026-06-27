"""
Route Router — POST /api/route-model and POST /api/route-task

Model routing and task workflow planning endpoints.
Requirements: 5.1, 5.7
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.domain.models import RoutingDecision, TaskRoute

router = APIRouter(prefix="/api", tags=["route"])


@router.post("/route-model", response_model=RoutingDecision)
async def route_model(req: Request, body: dict) -> RoutingDecision:
    """Route a task to the optimal model tier."""
    router_service = getattr(req.app.state, "router_service", None)
    if router_service is None:
        raise HTTPException(status_code=503, detail="Router service not available")

    task = body.get("task", "")
    runtime = body.get("runtime")

    if not task or not task.strip():
        raise HTTPException(status_code=400, detail="Non-empty task description required")

    try:
        return await router_service.route_model(task, runtime)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/route-task", response_model=TaskRoute)
async def route_task(req: Request, body: dict) -> TaskRoute:
    """Route a task to a workflow plan."""
    router_service = getattr(req.app.state, "router_service", None)
    if router_service is None:
        raise HTTPException(status_code=503, detail="Router service not available")

    task = body.get("task", "")
    if not task or not task.strip():
        raise HTTPException(status_code=400, detail="Non-empty task description required")

    try:
        return await router_service.route_task(task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
