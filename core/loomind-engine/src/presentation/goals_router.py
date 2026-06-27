"""
Goals Router — Goal submission and task lifecycle endpoints.

GET  /api/goals                                  → list[GoalRecord] (all goals, for matrix view)
POST /api/goals                                  → GoalRecord (submit + decompose)
GET  /api/goals/{goal_id}                        → GoalRecord
GET  /api/goals/{goal_id}/tasks                  → list[TaskRecord]
POST /api/goals/{goal_id}/tasks/{task_id}/claim   → TaskRecord
POST /api/goals/{goal_id}/tasks/{task_id}/complete → TaskRecord
POST /api/goals/{goal_id}/tasks/{task_id}/fail    → TaskRecord

Phase 9C — Goal Decomposition.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.domain.models import (
    GoalRecord,
    GoalSubmitRequest,
    TaskClaimRequest,
    TaskCompleteRequest,
    TaskRecord,
)

router = APIRouter(prefix="/api/goals", tags=["goals"])


@router.get("", response_model=list[GoalRecord])
async def list_goals(req: Request, status: str | None = None, limit: int = 100) -> list[GoalRecord]:
    """List all goals — used by the Graph Task Matrix view."""
    svc = req.app.state.goal_service
    if svc.store:
        records = svc.store.list_goals(status=status)
        return records[:limit]
    return []


@router.post("", response_model=GoalRecord, status_code=201)
async def submit_goal(body: GoalSubmitRequest, req: Request) -> GoalRecord:
    """Submit a high-level goal. Engine decomposes it into tasks for the agent fleet."""
    svc = req.app.state.goal_service
    worktree_path: str | None = None
    if body.worktree_id and hasattr(req.app.state, "worktree_store"):
        wt = req.app.state.worktree_store.get(body.worktree_id)
        worktree_path = wt.path if wt else None
    return svc.submit_goal(body.goal, body.submitted_by, worktree_id=body.worktree_id, worktree_path=worktree_path)


@router.get("/{goal_id}", response_model=GoalRecord)
async def get_goal(goal_id: str, req: Request) -> GoalRecord:
    record = req.app.state.goal_service.get_goal(goal_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")
    return record


@router.get("/{goal_id}/tasks", response_model=list[TaskRecord])
async def get_tasks(goal_id: str, req: Request) -> list[TaskRecord]:
    tasks = req.app.state.goal_service.get_tasks(goal_id)
    if tasks is None:
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")
    return tasks


@router.post("/{goal_id}/tasks/{task_id}/claim", response_model=TaskRecord)
async def claim_task(goal_id: str, task_id: str, body: TaskClaimRequest, req: Request) -> TaskRecord:
    """Agent claims a pending task. Returns 409 if already claimed."""
    task = req.app.state.goal_service.claim_task(goal_id, task_id, body.agent_id)
    if task is None:
        raise HTTPException(status_code=409, detail="Task not found or already claimed")
    return task


@router.post("/{goal_id}/tasks/{task_id}/complete", response_model=TaskRecord)
async def complete_task(goal_id: str, task_id: str, body: TaskCompleteRequest, req: Request) -> TaskRecord:
    """Agent reports task completion. Automatically advances the goal pipeline."""
    task = req.app.state.goal_service.complete_task(goal_id, task_id, body.outcome, body.artifacts)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{goal_id}/tasks/{task_id}/fail", response_model=TaskRecord)
async def fail_task(goal_id: str, task_id: str, body: TaskCompleteRequest, req: Request) -> TaskRecord:
    """Agent reports task failure. Marks goal as failed."""
    task = req.app.state.goal_service.fail_task(goal_id, task_id, body.outcome)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
