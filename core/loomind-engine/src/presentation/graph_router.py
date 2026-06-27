"""
Graph Router — GET /api/graph

Returns 1-hop edges incident on a given experience.
Requirements: 4.1
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api", tags=["graph"])


@router.get("/graph")
async def get_graph(req: Request, experience_id: str = Query(..., description="Experience ID to query edges for")) -> dict:
    """Return 1-hop edges incident on the given experience."""
    if not experience_id or not experience_id.strip():
        raise HTTPException(status_code=400, detail="experience_id required")

    graph_service = getattr(req.app.state, "graph_service", None)
    if graph_service is None:
        raise HTTPException(status_code=503, detail="Graph service not available")

    qdrant = req.app.state.service.qdrant
    edges = qdrant.query_edges([experience_id])

    return {
        "experience_id": experience_id,
        "edges": [e.model_dump(mode="json") for e in edges],
        "count": len(edges),
    }
