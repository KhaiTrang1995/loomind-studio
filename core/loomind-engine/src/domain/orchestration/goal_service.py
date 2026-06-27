"""
Goal Service — BA-powered decomposition with HITL, priority queue, and SQLite persistence.

Flow (Phase 11 — Agentic Brain):
  analyze_and_submit(goal) → BAService decomposes → User Stories + AC + Fibonacci story points
  submit_goal()            → GoalRecord persisted to SQLite, tasks queued by priority
  Agent claims task        → exclusive atomic lock (no race condition)
  HITL tasks               → 180s timeout → auto-execute (never for SECURITY/DELETE)
  interrupted tasks        → resume from checkpoint (no restart)
  complete_task()          → PostTool trigger, next task auto-assigned
  All done                 → goal_completed SSE broadcast
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.domain.models import (
    CreateExperienceRequest,
    GoalRecord,
    TaskRecord,
    TaskStatus,
    TaskMode,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_SECURITY_MODES = {TaskMode.SECURITY}


class GoalService:
    """Persistent goal store with BA decomposition, HITL management, and priority queue."""

    # Claimed tasks must heartbeat within this window or are returned to PENDING
    CLAIM_TIMEOUT_SECONDS = 300  # 5 minutes

    def __init__(
        self,
        event_bus=None,
        agent_registry=None,
        goal_store=None,
        ba_service=None,
        notification_service=None,
        experience_service=None,
        hitl_timeout_seconds: int = 180,
    ) -> None:
        self.event_bus = event_bus
        self.agent_registry = agent_registry
        self.cli_registry = None  # set via set_cli_registry() after Phase 12 init
        self.store = goal_store
        self.ba_service = ba_service
        self.notifier = notification_service
        self.experience_service = experience_service
        self.hitl_timeout = hitl_timeout_seconds
        self._hitl_tasks: dict[str, asyncio.Task] = {}
        # Start background stuck-task sweeper
        asyncio.get_event_loop().call_soon(lambda: asyncio.create_task(self._stuck_task_sweeper()))

    def set_cli_registry(self, cli_registry) -> None:
        """Wire in the Phase 12 CLI fleet registry after both objects are initialized."""
        self.cli_registry = cli_registry

    # ── Goal lifecycle ───────────────────────────────────────────────────

    async def analyze_and_submit(
        self, goal: str, submitted_by: str,
        worktree_id: Optional[str] = None,
        worktree_path: Optional[str] = None,
    ) -> GoalRecord:
        """Full pipeline: BA analysis → persist → broadcast."""
        goal_id = str(uuid.uuid4())

        if self.ba_service:
            try:
                prior_context = self._search_similar_goals(goal)
                analysis = await self.ba_service.analyze_goal(
                    goal, goal_id=goal_id, prior_context=prior_context
                )
                tasks = [
                    TaskRecord(
                        goal_id=goal_id,
                        task_type=story.task_type,
                        description=f"[{story.title}] {story.description}",
                        mode=story.task_mode,
                        story_points=story.story_points,
                    )
                    for story in analysis.user_stories
                ]
                analysis_dict = analysis.model_dump(mode="json")
            except Exception as exc:
                logger.warning("BA analysis failed, using fallback pipeline: %s", exc)
                tasks = self._default_pipeline(goal, goal_id)
                analysis_dict = None
        else:
            tasks = self._default_pipeline(goal, goal_id)
            analysis_dict = None

        record = GoalRecord(
            goal_id=goal_id,
            goal=goal,
            submitted_by=submitted_by,
            tasks=tasks,
            status="planned",
            analysis=analysis_dict,
            worktree_id=worktree_id,
            worktree_path=worktree_path,
        )

        if self.store:
            self.store.save_goal(record)

        if self.event_bus:
            self.event_bus.broadcast({
                "event": "goal_created",
                "payload": {
                    "goal_id": goal_id,
                    "goal": goal,
                    "task_count": len(tasks),
                    "total_points": sum(t.story_points for t in tasks),
                    "worktree_id": worktree_id,
                },
            })

        logger.info("Goal %s created: %d tasks, submitted by %s (worktree=%s)", goal_id, len(tasks), submitted_by, worktree_id)
        self._try_auto_assign_next(record)
        return record

    def submit_goal(
        self, goal: str, submitted_by: str,
        worktree_id: Optional[str] = None,
        worktree_path: Optional[str] = None,
    ) -> GoalRecord:
        """Sync fallback — creates goal with default pipeline (no BA analysis)."""
        goal_id = str(uuid.uuid4())
        tasks = self._default_pipeline(goal, goal_id)
        record = GoalRecord(
            goal_id=goal_id,
            goal=goal,
            submitted_by=submitted_by,
            tasks=tasks,
            status="planned",
            worktree_id=worktree_id,
            worktree_path=worktree_path,
        )
        if self.store:
            self.store.save_goal(record)
        if self.event_bus:
            self.event_bus.broadcast({"event": "goal_created", "payload": {"goal_id": goal_id, "goal": goal, "worktree_id": worktree_id}})
        self._try_auto_assign_next(record)
        return record

    def get_goal(self, goal_id: str) -> Optional[GoalRecord]:
        if self.store:
            return self.store.get_goal(goal_id)
        return None

    def get_tasks(self, goal_id: str) -> list[TaskRecord]:
        record = self.get_goal(goal_id)
        return record.tasks if record else []

    # ── Task claim ───────────────────────────────────────────────────────

    def claim_task(self, goal_id: str, task_id: str, agent_id: str) -> Optional[TaskRecord]:
        """Atomic exclusive claim. Returns None if already taken or prerequisites unmet."""
        record = self.store.get_goal(goal_id) if self.store else None
        if not record:
            return None

        task = self._find_task(record, task_id)
        if not task:
            return None

        # Enforce sequential ordering — reject claim if prerequisites not done
        if not self._prerequisites_done(record, task):
            logger.info(
                "Claim rejected: task %s (%s) prerequisites not complete yet",
                task_id[:8], task.task_type,
            )
            return None

        # Reject agents that already exhausted retries on this task
        failed_by = getattr(task, "failed_by", [])
        if agent_id in failed_by:
            logger.warning(
                "Claim rejected: agent %s already exhausted retries on task %s",
                agent_id, task_id[:8],
            )
            return None

        if self.store:
            ok = self.store.claim_task_exclusive(goal_id, task_id, agent_id)
            if not ok:
                return None
            record = self.store.get_goal(goal_id)
            task = self._find_task(record, task_id) if record else None
        else:
            return None

        if task:
            logger.info("Task %s claimed by %s", task_id, agent_id)
            self._maybe_start_hitl_timer(task, goal_id)
        return task

    def _prerequisites_done(self, record: GoalRecord, task: TaskRecord) -> bool:
        """True if all task types that must complete before this one are done."""
        _ORDER = ["research", "code", "test", "evaluate"]
        try:
            task_pos = _ORDER.index(task.task_type)
        except ValueError:
            return True  # unknown type — no ordering constraint
        required = _ORDER[:task_pos]
        done_types = {t.task_type for t in record.tasks if t.status == TaskStatus.COMPLETED}
        for req_type in required:
            # Only enforce if a task of this type exists in the goal
            has_type = any(t.task_type == req_type for t in record.tasks)
            if has_type and req_type not in done_types:
                return False
        return True

    def approve_hitl(self, goal_id: str, task_id: str, approved: bool, comment: str = "") -> Optional[TaskRecord]:
        """SA approves or rejects a HITL task."""
        record = self.get_goal(goal_id)
        if not record:
            return None
        task = self._find_task(record, task_id)
        if not task or task.status != TaskStatus.HITL_PENDING:
            return None

        self._cancel_hitl_timer(task_id)

        if approved:
            task.status = TaskStatus.CLAIMED
            task.retry_count = 0  # fresh start after human review
            # Keep failed_by — blocked agents stay blocked even after human approval
            task.outcome = f"HITL approved: {comment}"
        else:
            task.status = TaskStatus.PENDING
            task.assigned_to = None
            task.retry_count = 0  # reset so next agent gets full retries
            task.hitl_deadline = None
            task.outcome = None
            # Keep failed_by — rejected agent still blocked

        if self.store:
            self.store.update_task(task)

        if self.event_bus and task.assigned_to:
            self.event_bus.publish(task.assigned_to, {
                "event": "hitl_resolved",
                "payload": {"task_id": task_id, "goal_id": goal_id, "approved": approved},
            })

        # When rejected, immediately re-broadcast so available agents can claim it
        if not approved:
            self._try_auto_assign_next(record)

        return task

    # ── Task progress ────────────────────────────────────────────────────

    def save_checkpoint(self, task_id: str, checkpoint: str) -> None:
        if self.store:
            self.store.save_checkpoint(task_id, checkpoint)

    MAX_ITERATIONS = 3  # max evaluate→revise cycles before accepting result

    def complete_task(self, goal_id: str, task_id: str, outcome: str, artifacts: dict = None) -> Optional[TaskRecord]:
        record = self.get_goal(goal_id)
        if not record:
            return None
        task = self._find_task(record, task_id)
        if task is None:
            return None

        task.status = TaskStatus.COMPLETED
        task.outcome = outcome
        task.artifacts = artifacts or {}
        task.completed_at = datetime.now(timezone.utc)

        if self.store:
            self.store.update_task(task)

        logger.info("Task %s completed by %s", task_id, task.assigned_to)
        asyncio.create_task(self._notify_task_done(task))

        if self.agent_registry and task.assigned_to:
            self.agent_registry.send_message(
                from_agent=task.assigned_to,
                to_agent="ba-orchestrator",
                content=f"Done [{task.task_type}]: {(outcome or '')[:120]}",
                context={"goal_id": goal_id, "task_id": task_id, "event": "task_completed"},
            )

        # Iteration loop — when evaluate says NEEDS_REVISION, spawn new cycle
        if task.task_type == "evaluate":
            iteration = self._count_completed_evaluations(record)
            if self._needs_revision(outcome, artifacts) and iteration < self.MAX_ITERATIONS:
                self._spawn_revision_tasks(record, task, outcome, iteration)
                return task

        next_task = self._next_pending(record)
        if next_task:
            self._try_auto_assign_next(record)
        else:
            self._finish_goal(record)

        return task

    # ── Iteration helpers ────────────────────────────────────────────────

    @staticmethod
    def _needs_revision(outcome: str, artifacts: Optional[dict]) -> bool:
        """True if evaluate output signals the work needs another cycle."""
        upper = (outcome or "").upper()
        # Explicit pass signals
        if any(kw in upper for kw in ("PASS", "APPROVED", "LGTM", "SHIP IT", "LOOKS GOOD")):
            return False
        # Explicit revision signals
        if any(kw in upper for kw in ("NEEDS_REVISION", "NEEDS REVISION", "FAIL", "NOT_READY",
                                       "NOT READY", "NEEDS_IMPROVEMENT", "REWORK")):
            return True
        # Low confidence from agent
        confidence = (artifacts or {}).get("confidence", 1.0)
        if isinstance(confidence, (int, float)) and confidence < 0.6:
            return True
        return False

    def _count_completed_evaluations(self, record: GoalRecord) -> int:
        return sum(
            1 for t in record.tasks
            if t.task_type == "evaluate" and t.status == TaskStatus.COMPLETED
        )

    def _spawn_revision_tasks(
        self,
        record: GoalRecord,
        evaluate_task: TaskRecord,
        feedback: str,
        iteration: int,
    ) -> None:
        """Add new code+test+evaluate tasks carrying the evaluator's feedback."""
        rev = iteration + 1
        feedback_snippet = (feedback or "")[:400]

        # Find original code task description for context
        orig_code = next(
            (t.description for t in record.tasks if t.task_type == "code"),
            f"Implement the solution for: {record.goal}",
        )
        orig_test = next(
            (t.description for t in record.tasks if t.task_type == "test"),
            f"Write and run tests for: {record.goal}",
        )
        orig_eval = next(
            (t.description for t in record.tasks if t.task_type == "evaluate"),
            f"Review quality for: {record.goal}",
        )

        new_tasks = [
            TaskRecord(
                goal_id=record.goal_id,
                task_type="code",
                description=(
                    f"[Revision {rev}] {orig_code}\n\n"
                    f"EVALUATION FEEDBACK TO ADDRESS:\n{feedback_snippet}"
                ),
                story_points=5,
                mode="auto",
            ),
            TaskRecord(
                goal_id=record.goal_id,
                task_type="test",
                description=f"[Revision {rev}] {orig_test}",
                story_points=2,
                mode="auto",
            ),
            TaskRecord(
                goal_id=record.goal_id,
                task_type="evaluate",
                description=f"[Revision {rev}] {orig_eval}",
                story_points=1,
                mode="auto",
            ),
        ]

        for t in new_tasks:
            if self.store:
                self.store.update_task(t)

        logger.info(
            "Goal %s: evaluate requested revision %d/%d — spawned 3 new tasks",
            record.goal_id, rev, self.MAX_ITERATIONS,
        )

        if self.event_bus:
            self.event_bus.broadcast({
                "event": "goal_revision",
                "payload": {
                    "goal_id": record.goal_id,
                    "revision": rev,
                    "max_revisions": self.MAX_ITERATIONS,
                    "feedback_snippet": feedback_snippet[:100],
                },
            })

        # Re-fetch record so next_pending sees the new tasks
        updated = self.get_goal(record.goal_id)
        if updated:
            self._try_auto_assign_next(updated)

    def fail_task(self, goal_id: str, task_id: str, reason: str) -> Optional[TaskRecord]:
        record = self.get_goal(goal_id)
        if not record:
            return None
        task = self._find_task(record, task_id)
        if task is None:
            return None

        task.retry_count = getattr(task, "retry_count", 0) + 1

        if task.retry_count < _MAX_RETRIES:
            task.status = TaskStatus.PENDING
            task.assigned_to = None
            logger.info("Task %s failed, retry %d/%d", task_id, task.retry_count, _MAX_RETRIES)
        else:
            # Record this agent as exhausted — block it from re-claiming
            if task.assigned_to:
                failed_by = list(getattr(task, "failed_by", []))
                if task.assigned_to not in failed_by:
                    failed_by.append(task.assigned_to)
                    task.failed_by = failed_by
            task.status = TaskStatus.FAILED
            task.outcome = reason
            task.completed_at = datetime.now(timezone.utc)
            logger.warning("Task %s permanently failed after %d retries", task_id, task.retry_count)
            self._escalate_to_hitl(record, task, f"Failed {_MAX_RETRIES} times: {reason}")

        if self.store:
            self.store.update_task(task)
        return task

    def resume_task(self, goal_id: str, task_id: str, agent_id: str) -> Optional[TaskRecord]:
        """Resume an interrupted task from its checkpoint — no restart, preserves context."""
        record = self.get_goal(goal_id)
        if not record:
            return None
        task = self._find_task(record, task_id)
        if task is None or task.status not in (TaskStatus.INTERRUPTED, TaskStatus.CLAIMED):
            return None
        task.assigned_to = agent_id
        task.status = TaskStatus.IN_PROGRESS
        if self.store:
            self.store.update_task(task)
        logger.info("Task %s resumed by %s (checkpoint: %s)", task_id, agent_id, bool(task.checkpoint))
        return task

    # ── HITL timer ───────────────────────────────────────────────────────

    def _maybe_start_hitl_timer(self, task: TaskRecord, goal_id: str) -> None:
        mode = getattr(task, "mode", TaskMode.AUTO)
        if mode in (TaskMode.HITL, TaskMode.SECURITY):
            task.status = TaskStatus.HITL_PENDING
            if mode == TaskMode.HITL:
                task.hitl_deadline = datetime.now(timezone.utc) + timedelta(seconds=self.hitl_timeout)
            if self.store:
                self.store.update_task(task)
            if mode == TaskMode.HITL:
                t = asyncio.create_task(self._hitl_timeout_handler(goal_id, task.task_id))
                self._hitl_tasks[task.task_id] = t
            asyncio.create_task(self._notify_hitl(task, is_security=(mode == TaskMode.SECURITY)))

    async def _hitl_timeout_handler(self, goal_id: str, task_id: str) -> None:
        await asyncio.sleep(self.hitl_timeout)
        record = self.get_goal(goal_id)
        if not record:
            return
        task = self._find_task(record, task_id)
        if not task or task.status != TaskStatus.HITL_PENDING:
            return
        if getattr(task, "mode", "") == TaskMode.SECURITY:
            return  # Never auto-escalate security tasks
        task.status = TaskStatus.CLAIMED
        task.hitl_deadline = None
        if self.store:
            self.store.update_task(task)
        logger.info("HITL task %s auto-escalated after %ds timeout", task_id, self.hitl_timeout)
        if self.event_bus:
            self.event_bus.publish(task.assigned_to or "__broadcast__", {
                "event": "hitl_escalated",
                "payload": {"task_id": task_id, "goal_id": goal_id},
            })
        if self.notifier:
            await self.notifier.notify_task_escalated(0)

    async def _stuck_task_sweeper(self) -> None:
        """Every 60s: release claimed tasks whose agent stopped heartbeating."""
        while True:
            await asyncio.sleep(60)
            if not self.store:
                continue
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.CLAIM_TIMEOUT_SECONDS)
                for record in self.store.list_goals():
                    for task in record.tasks:
                        if task.status not in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS):
                            continue
                        # Check if assigned agent is still alive (BA registry)
                        if task.assigned_to and self.agent_registry:
                            alive = any(
                                a.agent_id == task.assigned_to
                                for a in self.agent_registry.get_online()
                            )
                            if alive:
                                continue
                        # Also check CLI fleet registry (cli-agy → cli_type='agy')
                        if task.assigned_to and self.cli_registry:
                            cli_name = task.assigned_to.removeprefix("cli-")
                            rec = next(
                                (r for r in self.cli_registry.get_fleet()
                                 if r.cli_type == cli_name),
                                None,
                            )
                            if rec and rec.status in ("online", "busy", "idle"):
                                continue  # CLI agent alive — do NOT release
                        # Agent offline/unknown — use cutoff based on when last seen
                        # Fall back to created_at only if we have no better signal
                        age = datetime.now(timezone.utc) - task.created_at.replace(tzinfo=timezone.utc) \
                            if task.created_at.tzinfo is None else \
                            datetime.now(timezone.utc) - task.created_at
                        if age.total_seconds() > self.CLAIM_TIMEOUT_SECONDS:
                            task.status = TaskStatus.PENDING
                            task.assigned_to = None
                            if self.store:
                                self.store.update_task(task)
                            logger.warning(
                                "Stuck task %s released back to PENDING (agent offline/timeout)",
                                task.task_id,
                            )
                            self._try_auto_assign_next(record)
            except Exception:
                logger.exception("Stuck-task sweeper error")

    def _cancel_hitl_timer(self, task_id: str) -> None:
        t = self._hitl_tasks.pop(task_id, None)
        if t:
            t.cancel()

    def _escalate_to_hitl(self, record: GoalRecord, task: TaskRecord, reason: str) -> None:
        task.status = TaskStatus.HITL_PENDING
        task.mode = TaskMode.HITL
        task.hitl_deadline = datetime.now(timezone.utc) + timedelta(seconds=self.hitl_timeout)
        if self.store:
            self.store.update_task(task)
        # Start 180s auto-proceed timer (never fires for SECURITY)
        t = asyncio.create_task(self._hitl_timeout_handler(record.goal_id, task.task_id))
        self._hitl_tasks[task.task_id] = t
        if self.event_bus:
            self.event_bus.broadcast({
                "event": "task_needs_review",
                "payload": {"goal_id": record.goal_id, "task_id": task.task_id, "reason": reason},
            })

    # ── Notification helpers ─────────────────────────────────────────────

    async def _notify_hitl(self, task: TaskRecord, is_security: bool = False) -> None:
        if self.notifier:
            await self.notifier.notify_task_hitl(0, task.description[:80], self.hitl_timeout)

    async def _notify_task_done(self, task: TaskRecord) -> None:
        if self.notifier:
            await self.notifier.notify_task_completed(0, task.description[:80])

    # ── Goal finalization ────────────────────────────────────────────────

    def _finish_goal(self, record: GoalRecord) -> None:
        record.status = "done"
        if self.store:
            self.store.update_goal_status(record.goal_id, "done")
        logger.info("Goal %s fully completed", record.goal_id)
        if self.event_bus:
            self.event_bus.broadcast({
                "event": "goal_completed",
                "payload": {"goal_id": record.goal_id, "goal": record.goal},
            })
        if self.notifier:
            asyncio.create_task(self.notifier.notify_goal_done(record.goal))
        self._save_goal_pattern(record)

    def _save_goal_pattern(self, record: GoalRecord) -> None:
        """Persist completed goal as a reusable decomposition pattern in the knowledge base.

        Future BA analyses will surface similar patterns via intercept search so they
        can calibrate story points and task types against real historical data.
        """
        if not self.experience_service:
            return
        completed = [t for t in record.tasks if t.status == TaskStatus.COMPLETED]
        evaluate_cycles = sum(1 for t in completed if t.task_type == "evaluate")
        task_type_summary = ", ".join(
            f"{tt}×{sum(1 for t in completed if t.task_type == tt)}"
            for tt in ["research", "code", "test", "evaluate"]
            if any(t.task_type == tt for t in completed)
        )
        total_points = sum(getattr(t, "story_points", 1) for t in record.tasks)
        avg_conf = (
            sum(
                (t.artifacts or {}).get("confidence", 0.7)
                for t in completed if t.artifacts
            ) / max(1, sum(1 for t in completed if t.artifacts))
        )
        description = (
            f"GOAL: {record.goal}\n"
            f"Tasks completed: {len(completed)} ({task_type_summary})\n"
            f"Total story points: {total_points}\n"
            f"Evaluate cycles: {evaluate_cycles} "
            f"({'needed revision' if evaluate_cycles > 1 else 'passed first cycle'})\n"
            f"Avg agent confidence: {avg_conf:.2f}\n"
            f"Submitted by: {record.submitted_by}"
        )
        try:
            self.experience_service.create_experience(CreateExperienceRequest(
                title=f"Goal pattern: {record.goal[:70]}",
                description=description,
                category="goal-pattern",
                tags=["goal-pattern", "decomposition", "autonomous", record.submitted_by or "agent"],
            ))
            logger.info("Saved goal pattern for goal %s (%d tasks, %d eval cycles)",
                        record.goal_id[:8], len(completed), evaluate_cycles)
        except Exception as exc:
            logger.warning("Could not save goal pattern: %s", exc)

    def _search_similar_goals(self, goal: str) -> str:
        """Return top-3 past goal patterns similar to this goal, formatted for BA prompt."""
        if not self.experience_service:
            return ""
        try:
            hits = self.experience_service.search_experiences(goal, top_k=3)
            pattern_hits = [h for h in hits if "goal-pattern" in (h.tags or [])][:3]
            if not pattern_hits:
                return ""
            lines = [f"- {h.title}: {h.description[:300]}" for h in pattern_hits]
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("Similar-goal search failed: %s", exc)
            return ""

    # ── Auto-assign ──────────────────────────────────────────────────────

    def _try_auto_assign_next(self, record: GoalRecord) -> None:
        if not self.event_bus:
            return
        next_task = self._next_pending(record)
        if not next_task:
            return
        candidate = None
        if self.agent_registry:
            candidates = self.agent_registry.get_by_role(next_task.task_type)
            if candidates:
                candidate = candidates[0].agent_id
        payload = {
            "goal_id": record.goal_id,
            "task_id": next_task.task_id,
            "task_type": next_task.task_type,
            "description": next_task.description,
            "story_points": getattr(next_task, "story_points", 1),
            "mode": getattr(next_task, "mode", "auto"),
        }
        if candidate:
            self.event_bus.publish(candidate, {"event": "task_assigned", "payload": payload})
            if self.agent_registry:
                self.agent_registry.send_message(
                    from_agent="ba-orchestrator",
                    to_agent=candidate,
                    content=f"[{next_task.task_type}] {next_task.description[:120]}",
                    context={"goal_id": record.goal_id, "task_id": next_task.task_id, "event": "task_assigned"},
                )
        else:
            self.event_bus.broadcast({"event": "task_available", "payload": payload})

    # ── Utilities ────────────────────────────────────────────────────────

    def _find_task(self, record: Optional[GoalRecord], task_id: str) -> Optional[TaskRecord]:
        if not record:
            return None
        for t in record.tasks:
            if t.task_id == task_id:
                return t
        return None

    def _next_pending(self, record: GoalRecord) -> Optional[TaskRecord]:
        """Return next task that is PENDING and whose prerequisites are all done.

        Sequential order: research must complete before code starts,
        code before test, test before evaluate. This prevents agents from
        jumping ahead and running evaluate before code exists.
        """
        _ORDER = ["research", "code", "test", "evaluate"]
        done_types = {
            t.task_type
            for t in record.tasks
            if t.status == TaskStatus.COMPLETED
        }
        in_progress_types = {
            t.task_type
            for t in record.tasks
            if t.status in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS, TaskStatus.HITL_PENDING)
        }

        for task_type in _ORDER:
            # Skip if a task of this type is already running or done
            if task_type in done_types or task_type in in_progress_types:
                continue
            # Find a pending task of this type
            for t in record.tasks:
                if t.task_type == task_type and t.status == TaskStatus.PENDING:
                    return t
            # This type has no pending task → continue to next type

        # Fallback: any pending task not in the standard order
        for t in record.tasks:
            if t.status == TaskStatus.PENDING:
                return t
        return None

    def _default_pipeline(self, goal: str, goal_id: str) -> list[TaskRecord]:
        pipeline = [
            ("research", f"Research and gather context for: {goal}", 3, "auto"),
            ("code",     f"Implement the solution for: {goal}",     5, "auto"),
            ("test",     f"Write and run tests for: {goal}",        2, "auto"),
            ("evaluate", f"Review quality and correctness for: {goal}", 1, "auto"),
        ]
        return [
            TaskRecord(goal_id=goal_id, task_type=tt, description=desc, story_points=pts, mode=mode)
            for tt, desc, pts, mode in pipeline
        ]
