"""
Worktree Store — JSON-backed registry of host repository paths for scoped task execution.

Each WorktreeRecord maps a friendly name to an absolute host path.
agent_loop.py reads worktree_path from GoalRecord and sets it as cwd when calling CLIs.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from src.domain.models import WorktreeRecord, WorktreeCreateRequest, WorktreePatchRequest

logger = logging.getLogger(__name__)


class WorktreeStore:
    """Persist worktrees in data/worktrees.json — simple list, no database needed."""

    def __init__(self, path: str = "./data/worktrees.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, WorktreeRecord] = {}
        self._load()

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create(self, req: WorktreeCreateRequest) -> WorktreeRecord:
        record = WorktreeRecord(name=req.name, path=req.path, description=req.description)
        self._records[record.worktree_id] = record
        self._save()
        logger.info("Worktree registered: %s → %s", record.name, record.path)
        return record

    def get(self, worktree_id: str) -> Optional[WorktreeRecord]:
        return self._records.get(worktree_id)

    def list_all(self) -> list[WorktreeRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)

    def patch(self, worktree_id: str, req: WorktreePatchRequest) -> Optional[WorktreeRecord]:
        record = self._records.get(worktree_id)
        if not record:
            return None
        if req.name is not None:
            record.name = req.name
        if req.description is not None:
            record.description = req.description
        if req.active is not None:
            record.active = req.active
        self._save()
        return record

    def delete(self, worktree_id: str) -> bool:
        if worktree_id not in self._records:
            return False
        del self._records[worktree_id]
        self._save()
        return True

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        data = [r.model_dump(mode="json") for r in self._records.values()]
        self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for item in data:
                record = WorktreeRecord.model_validate(item)
                self._records[record.worktree_id] = record
            logger.info("Loaded %d worktrees from %s", len(self._records), self._path)
        except Exception as exc:
            logger.warning("Failed to load worktrees: %s", exc)
