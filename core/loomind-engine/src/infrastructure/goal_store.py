"""
Goal Store — SQLite-backed persistence for GoalRecord and TaskRecord.

Stores goal/task state so it survives engine restarts and prevents RAM overflow.
Uses WAL mode for safe concurrent reads from multiple agents.

Phase 11 — Agentic Brain.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from src.domain.models import GoalRecord, TaskRecord, TaskStatus

logger = logging.getLogger(__name__)

_CREATE_GOALS = """
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    goal    TEXT NOT NULL,
    submitted_by TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'pending',
    analysis TEXT,
    created_at TEXT NOT NULL,
    worktree_id TEXT,
    worktree_path TEXT
)"""

_CREATE_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    goal_id     TEXT NOT NULL,
    task_type   TEXT NOT NULL,
    description TEXT NOT NULL,
    assigned_to TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    mode        TEXT NOT NULL DEFAULT 'auto',
    story_points INTEGER NOT NULL DEFAULT 1,
    retry_count INTEGER NOT NULL DEFAULT 0,
    checkpoint  TEXT,
    hitl_deadline TEXT,
    outcome     TEXT,
    artifacts   TEXT NOT NULL DEFAULT '{}',
    failed_by   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (goal_id) REFERENCES goals(goal_id)
)"""


class GoalStore:
    """Persistent SQLite store for goals and tasks."""

    def __init__(self, db_path: str = "./data/goals.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_GOALS)
            conn.execute(_CREATE_TASKS)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            # Migration: add failed_by column if it doesn't exist yet
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN failed_by TEXT NOT NULL DEFAULT '[]'")
                logger.info("Migration: added failed_by column to tasks table")
            except Exception:
                pass  # column already exists
            # Migration: add worktree columns to goals
            try:
                conn.execute("ALTER TABLE goals ADD COLUMN worktree_id TEXT")
                conn.execute("ALTER TABLE goals ADD COLUMN worktree_path TEXT")
                logger.info("Migration: added worktree_id/worktree_path columns to goals table")
            except Exception:
                pass  # columns already exist

    # ── Goal operations ──────────────────────────────────────────────────

    def save_goal(self, record: GoalRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO goals
                   (goal_id, goal, submitted_by, status, analysis, created_at, worktree_id, worktree_path)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    record.goal_id,
                    record.goal,
                    record.submitted_by,
                    record.status,
                    json.dumps(record.analysis) if record.analysis else None,
                    record.created_at.isoformat(),
                    record.worktree_id,
                    record.worktree_path,
                ),
            )
            for task in record.tasks:
                self._upsert_task(conn, task)

    def update_goal_status(self, goal_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE goals SET status=? WHERE goal_id=?", (status, goal_id))

    def get_goal(self, goal_id: str) -> Optional[GoalRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM goals WHERE goal_id=?", (goal_id,)).fetchone()
            if not row:
                return None
            tasks = self._load_tasks(conn, goal_id)
            return self._row_to_goal(row, tasks)

    def list_goals(self, status: Optional[str] = None) -> list[GoalRecord]:
        with self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM goals WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
            return [self._row_to_goal(r, self._load_tasks(conn, r["goal_id"])) for r in rows]

    # ── Task operations ──────────────────────────────────────────────────

    def update_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            self._upsert_task(conn, task)

    def claim_task_exclusive(self, goal_id: str, task_id: str, agent_id: str) -> bool:
        """Atomic claim — returns True only if this agent successfully claimed the task."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE tasks SET assigned_to=?, status=? WHERE task_id=? AND goal_id=? AND status=?",
                (agent_id, TaskStatus.CLAIMED, task_id, goal_id, TaskStatus.PENDING),
            )
            return cur.rowcount == 1

    def claim_hitl_task(self, task_id: str, hitl_deadline: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status=?, hitl_deadline=? WHERE task_id=? AND status=?",
                (TaskStatus.HITL_PENDING, hitl_deadline, task_id, TaskStatus.PENDING),
            )
            return cur.rowcount == 1

    def get_pending_hitl_tasks(self) -> list[TaskRecord]:
        """Return HITL tasks whose deadline has passed (for auto-escalation check)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status=? AND hitl_deadline IS NOT NULL AND hitl_deadline < datetime('now')",
                (TaskStatus.HITL_PENDING,),
            ).fetchall()
            return [self._row_to_task(r) for r in rows]

    def next_pending_task(self, goal_id: str) -> Optional[TaskRecord]:
        """Priority queue: highest story_points first, then FIFO."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE goal_id=? AND status=? ORDER BY story_points DESC, created_at ASC LIMIT 1",
                (goal_id, TaskStatus.PENDING),
            ).fetchone()
            return self._row_to_task(row) if row else None

    def save_checkpoint(self, task_id: str, checkpoint: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE tasks SET checkpoint=?, status=? WHERE task_id=?",
                         (checkpoint, TaskStatus.IN_PROGRESS, task_id))

    # ── Private helpers ──────────────────────────────────────────────────

    def _upsert_task(self, conn: sqlite3.Connection, task: TaskRecord) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO tasks
               (task_id, goal_id, task_type, description, assigned_to, status,
                mode, story_points, retry_count, checkpoint, hitl_deadline,
                outcome, artifacts, failed_by, created_at, completed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task.task_id, task.goal_id, task.task_type, task.description,
                task.assigned_to, task.status,
                getattr(task, "mode", "auto"),
                getattr(task, "story_points", 1),
                getattr(task, "retry_count", 0),
                getattr(task, "checkpoint", None),
                getattr(task, "hitl_deadline", None),
                task.outcome,
                json.dumps(task.artifacts),
                json.dumps(getattr(task, "failed_by", [])),
                task.created_at.isoformat(),
                task.completed_at.isoformat() if task.completed_at else None,
            ),
        )

    def _load_tasks(self, conn: sqlite3.Connection, goal_id: str) -> list[TaskRecord]:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE goal_id=? ORDER BY story_points DESC, created_at ASC",
            (goal_id,),
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def _row_to_task(self, row: sqlite3.Row) -> TaskRecord:
        from datetime import datetime, timezone

        def _dt(s):
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc) if s else None

        return TaskRecord(
            task_id=row["task_id"],
            goal_id=row["goal_id"],
            task_type=row["task_type"],
            description=row["description"],
            assigned_to=row["assigned_to"],
            status=TaskStatus(row["status"]),
            mode=row["mode"],
            story_points=row["story_points"],
            retry_count=row["retry_count"],
            checkpoint=row["checkpoint"],
            hitl_deadline=_dt(row["hitl_deadline"]),
            outcome=row["outcome"],
            artifacts=json.loads(row["artifacts"] or "{}"),
            failed_by=json.loads(row["failed_by"] if "failed_by" in row.keys() else "[]"),
            created_at=_dt(row["created_at"]),
            completed_at=_dt(row["completed_at"]),
        )

    def _row_to_goal(self, row: sqlite3.Row, tasks: list[TaskRecord]) -> GoalRecord:
        from datetime import datetime, timezone
        keys = row.keys()
        return GoalRecord(
            goal_id=row["goal_id"],
            goal=row["goal"],
            submitted_by=row["submitted_by"],
            status=row["status"],
            analysis=json.loads(row["analysis"]) if row["analysis"] else None,
            tasks=tasks,
            created_at=datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc),
            worktree_id=row["worktree_id"] if "worktree_id" in keys else None,
            worktree_path=row["worktree_path"] if "worktree_path" in keys else None,
        )
