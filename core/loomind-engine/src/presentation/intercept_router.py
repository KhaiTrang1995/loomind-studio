"""
Intercept Router — POST /api/intercept
Main endpoint that the VS Code extension calls to get suggestions.

Returns InterceptResponseV2 which is backward-compatible with v1.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.domain.models import InterceptRequest, InterceptResponseV2

router = APIRouter(prefix="/api", tags=["intercept"])


@router.post("/intercept", response_model=InterceptResponseV2)
async def intercept(request: InterceptRequest, req: Request) -> InterceptResponseV2:
    """Process an intercept request through the v2 pipeline.

    v1 backward-compatible: all original fields present.
    v2 additions: trace_id, intent, enriched_action, tier_breakdown.
    """
    limiter = getattr(req.app.state, "intercept_rate_limiter", None)
    if limiter:
        client_ip = req.client.host if req.client else "unknown"
        allowed, retry_after = limiter.check(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"error": "Rate limit exceeded", "retry_after": retry_after},
            )

    service = req.app.state.service
    return await service.intercept(request)
