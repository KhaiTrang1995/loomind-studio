"""
BA Agent Router — Endpoints for goal analysis, HITL approval, and notification config.

Phase 11 — Agentic Brain.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.domain.models import (
    BAAnalyzeRequest,
    BAAnalysisResult,
    GoalRecord,
    GoalSubmitRequest,
    HITLApproveRequest,
    NotificationConfig,
    NotificationConfigUpdateRequest,
    TaskRecord,
)

router = APIRouter(prefix="/api/ba", tags=["Agentic Brain"])


# ── BA Analysis ──────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=GoalRecord)
async def analyze_goal(req: BAAnalyzeRequest, request: Request) -> GoalRecord:
    """
    Analyze a goal with BA Agent: decompose into User Stories, AC, and Fibonacci story points.
    Creates a GoalRecord and persists it. Broadcasts goal_created SSE event.
    """
    goal_service = request.app.state.goal_service
    worktree_path: str | None = None
    if req.worktree_id and hasattr(request.app.state, "worktree_store"):
        wt = request.app.state.worktree_store.get(req.worktree_id)
        worktree_path = wt.path if wt else None
    record = await goal_service.analyze_and_submit(
        req.goal, req.submitted_by,
        worktree_id=req.worktree_id, worktree_path=worktree_path,
    )
    return record


@router.get("/analyze/{goal_id}", response_model=BAAnalysisResult | None)
async def get_analysis(goal_id: str, request: Request):
    """Get the BA analysis result for a goal (user stories, AC, story points)."""
    goal_service = request.app.state.goal_service
    record = goal_service.get_goal(goal_id)
    if not record:
        raise HTTPException(404, "Goal not found")
    if not record.analysis:
        return None
    return record.analysis


# ── HITL Management ──────────────────────────────────────────────────────────

@router.post("/goals/{goal_id}/tasks/{task_id}/approve")
async def approve_hitl(
    goal_id: str,
    task_id: str,
    req: HITLApproveRequest,
    request: Request,
) -> TaskRecord:
    """
    SA approves or rejects a HITL task.
    - approved=true  → task proceeds to execute
    - approved=false → task returns to queue for re-evaluation
    """
    goal_service = request.app.state.goal_service
    task = goal_service.approve_hitl(goal_id, task_id, req.approved, req.comment)
    if not task:
        raise HTTPException(404, "Task not found or not in HITL_PENDING state")
    return task


@router.post("/goals/{goal_id}/tasks/{task_id}/checkpoint")
async def save_checkpoint(
    goal_id: str,
    task_id: str,
    request: Request,
    body: dict = None,
) -> dict:
    """Agent saves a checkpoint to enable resume-on-interrupt (no restart)."""
    body = body or {}
    checkpoint = body.get("checkpoint", "")
    if not checkpoint:
        raise HTTPException(400, "checkpoint field required")
    goal_service = request.app.state.goal_service
    goal_service.save_checkpoint(task_id, checkpoint)
    return {"ok": True, "task_id": task_id}


@router.post("/goals/{goal_id}/tasks/{task_id}/resume")
async def resume_task(
    goal_id: str,
    task_id: str,
    request: Request,
    body: dict = None,
) -> TaskRecord:
    """Resume an interrupted task from its checkpoint — preserves context, no token waste."""
    body = body or {}
    agent_id = body.get("agent_id", "unknown")
    goal_service = request.app.state.goal_service
    task = goal_service.resume_task(goal_id, task_id, agent_id)
    if not task:
        raise HTTPException(404, "Task not found or cannot be resumed")
    return task


# ── Notification Config ──────────────────────────────────────────────────────

@router.get("/notifications/config", response_model=NotificationConfig)
async def get_notification_config(request: Request) -> NotificationConfig:
    """Get current notification config (feature flag + webhook URLs)."""
    notifier = request.app.state.notification_service
    return notifier.get_config()


@router.patch("/notifications/config", response_model=NotificationConfig)
async def update_notification_config(
    req: NotificationConfigUpdateRequest,
    request: Request,
) -> NotificationConfig:
    """
    Update notification config — partial update supported.
    Toggle feature flag ON/OFF, add/remove webhook URLs, set Telegram credentials.
    """
    notifier = request.app.state.notification_service
    update = req.model_dump(exclude_none=True)
    return notifier.update_config(update)


@router.post("/notifications/toggle")
async def toggle_notifications(request: Request, body: dict = None) -> dict:
    """Quick toggle for notification feature flag (for MCP tool use)."""
    body = body or {}
    enabled = body.get("enabled")
    if enabled is None:
        raise HTTPException(400, "enabled field required")
    notifier = request.app.state.notification_service
    notifier.set_enabled(bool(enabled))
    return {"ok": True, "enabled": bool(enabled)}


@router.post("/notifications/test")
async def test_notification(request: Request) -> dict:
    """Send a test notification to verify webhook/Telegram config."""
    notifier = request.app.state.notification_service
    if not notifier.enabled:
        return {"ok": False, "message": "Notifications are disabled. Enable first."}
    await notifier._send("[Loomind] ✅ Test notification — kết nối thành công!")
    return {"ok": True, "message": "Test notification sent"}
