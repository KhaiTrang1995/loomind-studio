"""
Experience Router — CRUD endpoints for managing experiences.
"""

from fastapi import APIRouter, HTTPException, Request

from src.domain.models import (
    CreateExperienceRequest,
    Experience,
    ExportBundle,
    FeedbackRequest,
    ImportRequest,
    ImportResult,
    PaginatedResponse,
    UpdateExperienceRequest,
)

router = APIRouter(prefix="/api/experiences", tags=["experiences"])


@router.get("", response_model=PaginatedResponse)
async def list_experiences(req: Request, limit: int = 20, offset: int = 0) -> PaginatedResponse:
    """List all experiences with pagination."""
    service = req.app.state.service
    items, total = service.list_experiences(limit=limit, offset=offset)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=Experience)
async def create_experience(body: CreateExperienceRequest, req: Request) -> Experience:
    """Create a new experience."""
    service = req.app.state.service
    return service.create_experience(body)


@router.get("/{exp_id}", response_model=Experience)
async def get_experience(exp_id: str, req: Request) -> Experience:
    """Get an experience by ID."""
    service = req.app.state.service
    exp = service.get_experience(exp_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experience not found")
    return exp


@router.put("/{exp_id}", response_model=Experience)
async def update_experience(exp_id: str, body: UpdateExperienceRequest, req: Request) -> Experience:
    """Update an existing experience."""
    service = req.app.state.service
    exp = service.update_experience(exp_id, body)
    if not exp:
        raise HTTPException(status_code=404, detail="Experience not found")
    return exp


@router.delete("/{exp_id}")
async def delete_experience(exp_id: str, req: Request) -> dict:
    """Delete an experience."""
    service = req.app.state.service
    if not service.delete_experience(exp_id):
        raise HTTPException(status_code=404, detail="Experience not found")
    return {"deleted": True, "id": exp_id}


@router.post("/search", response_model=list[Experience])
async def search_experiences(req: Request, query: str = "") -> list[Experience]:
    """Search experiences by text similarity."""
    service = req.app.state.service
    return service.search_experiences(query)


@router.post("/{exp_id}/feedback")
async def submit_feedback(exp_id: str, body: FeedbackRequest, req: Request) -> dict:
    """Submit feedback for an experience."""
    service = req.app.state.service
    if not service.submit_feedback(exp_id, body):
        raise HTTPException(status_code=404, detail="Experience not found")
    return {"updated": True, "id": exp_id}


# ==================== Import / Export ====================


@router.get("/backup/export", response_model=ExportBundle)
async def export_experiences(req: Request) -> ExportBundle:
    """Export ALL experiences as a JSON bundle for backup/migration.

    Download this JSON and store it safely. Use /import to restore.
    """
    service = req.app.state.service
    experiences = service.export_all()
    return ExportBundle(
        total=len(experiences),
        experiences=experiences,
    )


@router.post("/backup/import", response_model=ImportResult)
async def import_experiences(body: ImportRequest, req: Request) -> ImportResult:
    """Import experiences from a JSON backup.

    Accepts either:
    - A full ExportBundle (with `experiences` array)
    - A plain list of experience objects

    Set `overwrite=true` to replace existing experiences with same ID.
    Default behavior skips duplicates.
    """
    service = req.app.state.service
    result = service.import_experiences(
        body.experiences, overwrite=body.overwrite
    )
    return ImportResult(**result)
