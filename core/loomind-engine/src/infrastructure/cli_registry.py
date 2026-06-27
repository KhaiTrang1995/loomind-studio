"""
CLI Registry — fleet status tracker for external CLI tools.

Tracks process-level state (busy/idle/offline) separately from
AgentRegistry (which tracks registered *sessions*). The CLIRegistry
is the single source of truth for "which CLI can accept a task now."

Phase 12 — Multi-CLI Fleet.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from src.domain.models import CLIType, CLIStatus, CLIStatusRecord

logger = logging.getLogger(__name__)


class CLIRegistry:
    """In-memory fleet status for all supported CLI tools."""

    # Default routing: which CLIs to use for each task type
    TASK_ROUTING: dict[str, list[str]] = {
        "research":   ["grok", "claude"],
        "code":       ["codex", "claude"],
        "review":     ["claude", "grok"],
        "security":   ["claude"],          # SECURITY → claude ONLY, HITL mandatory
        "ba_analyze": ["claude"],
        "test":       ["codex", "claude"],
        "general":    ["agy", "claude"],
    }

    # Default consultants per initiator for deliberations
    CONSULTANT_MAP: dict[str, list[str]] = {
        "claude": ["grok", "codex"],
        "grok":   ["claude", "codex"],
        "codex":  ["claude", "grok"],
        "agy":    ["claude", "grok"],
    }

    def __init__(self) -> None:
        self._fleet: dict[str, CLIStatusRecord] = {
            cli.value: CLIStatusRecord(cli_type=cli, status=CLIStatus.OFFLINE)
            for cli in CLIType
        }

    # ── Status management ─────────────────────────────────────────────────────

    def set_online(self, cli: str) -> None:
        """Mark a CLI as online/idle (registered itself via hook)."""
        self._update(cli, CLIStatus.ONLINE)
        logger.info("Fleet: %s → ONLINE", cli)

    def set_busy(self, cli: str, task: str, deliberation_id: Optional[str] = None, pid: Optional[int] = None) -> None:
        self._update(cli, CLIStatus.BUSY, task=task, deliberation_id=deliberation_id, pid=pid)
        logger.debug("Fleet: %s → BUSY (%s)", cli, task[:60])

    def set_idle(self, cli: str) -> None:
        rec = self._fleet.get(cli)
        if rec:
            rec.tasks_completed += 1
        self._update(cli, CLIStatus.IDLE)
        logger.debug("Fleet: %s → IDLE", cli)

    def set_offline(self, cli: str) -> None:
        self._update(cli, CLIStatus.OFFLINE)
        logger.info("Fleet: %s → OFFLINE", cli)

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_fleet(self) -> list[CLIStatusRecord]:
        return list(self._fleet.values())

    def is_available(self, cli: str) -> bool:
        rec = self._fleet.get(cli)
        return rec is not None and rec.status in (CLIStatus.ONLINE, CLIStatus.IDLE)

    def pick_for_task(self, task_type: str) -> Optional[str]:
        """Return the first available CLI for the given task type."""
        candidates = self.TASK_ROUTING.get(task_type, ["claude"])
        for cli in candidates:
            if self.is_available(cli):
                return cli
        return None

    def pick_consultants(self, initiator: str, preferred: Optional[list[str]] = None) -> list[str]:
        """Return available consultant CLIs for a deliberation, excluding initiator."""
        candidates = preferred or self.CONSULTANT_MAP.get(initiator, ["claude", "grok"])
        return [c for c in candidates if c != initiator]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _update(
        self,
        cli: str,
        status: CLIStatus,
        task: Optional[str] = None,
        deliberation_id: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> None:
        rec = self._fleet.get(cli)
        if rec is None:
            return
        rec.status = status
        rec.current_task = task
        rec.current_deliberation_id = deliberation_id
        if pid is not None:
            rec.pid = pid
        rec.last_seen = datetime.now(timezone.utc)
