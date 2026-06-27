"""
Agent Registry — In-memory registry with TTL for agentic orchestration.

Agents register on startup and send heartbeats to remain visible.
The registry is ephemeral: entries expire after AGENT_TTL_SECONDS of silence
and agents must re-register after an engine restart.

Phase 9B — Agent Identity.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from src.domain.models import AgentInfo, AgentRole

logger = logging.getLogger(__name__)

AGENT_TTL_SECONDS: float = 120.0


class AgentRegistry:
    """In-memory agent registry with passive TTL expiry."""

    def __init__(self) -> None:
        self._agents: dict[str, tuple[AgentInfo, float]] = {}  # agent_id → (info, last_seen_mono)
        self._messages: dict[str, list] = {}  # to_agent_id → list[AgentMessage]

    def register(self, agent_id: str, role: AgentRole, capabilities: list[str]) -> AgentInfo:
        """Register a new agent or refresh an existing one."""
        now = datetime.now(timezone.utc)
        info = AgentInfo(
            agent_id=agent_id,
            role=role,
            capabilities=capabilities,
            registered_at=now,
            last_seen=now,
        )
        self._agents[agent_id] = (info, time.monotonic())
        logger.info("Agent registered: %s (role=%s)", agent_id, role)
        return info

    def heartbeat(self, agent_id: str) -> bool:
        """Refresh a registered agent's TTL. Returns False if agent is unknown."""
        if agent_id not in self._agents:
            return False
        info, _ = self._agents[agent_id]
        info.last_seen = datetime.now(timezone.utc)
        self._agents[agent_id] = (info, time.monotonic())
        return True

    def deregister(self, agent_id: str) -> bool:
        """Remove an agent from the registry. Returns False if not found."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            logger.info("Agent deregistered: %s", agent_id)
            return True
        return False

    def get_online(self) -> list[AgentInfo]:
        """Return agents whose TTL has not expired."""
        cutoff = time.monotonic() - AGENT_TTL_SECONDS
        online = []
        for agent_id, (info, last_seen) in list(self._agents.items()):
            if last_seen >= cutoff:
                online.append(info)
            else:
                del self._agents[agent_id]
        return online

    def get_by_role(self, role: AgentRole | str) -> list[AgentInfo]:
        """Return online agents matching the given role."""
        role_val = role.value if isinstance(role, AgentRole) else role
        return [a for a in self.get_online() if a.role.value == role_val]

    def get(self, agent_id: str) -> AgentInfo | None:
        """Return a specific agent's info if online."""
        cutoff = time.monotonic() - AGENT_TTL_SECONDS
        entry = self._agents.get(agent_id)
        if entry and entry[1] >= cutoff:
            return entry[0]
        return None

    # ── Message store (Phase 10) ──────────────────────────────────────────

    def send_message(self, from_agent: str, to_agent: str, content: str, context: dict) -> "AgentMessage":
        from src.domain.models import AgentMessage
        msg = AgentMessage(from_agent=from_agent, to_agent=to_agent, content=content, context=context)
        if to_agent not in self._messages:
            self._messages[to_agent] = []
        self._messages[to_agent].append(msg)
        logger.info("Message %s → %s", from_agent, to_agent)
        return msg

    def get_messages(self, agent_id: str, unread_only: bool = True) -> list:
        msgs = self._messages.get(agent_id, [])
        if unread_only:
            msgs = [m for m in msgs if not m.read]
        return msgs

    def mark_read(self, agent_id: str, msg_id: str | None = None) -> int:
        """Mark all (or one specific) messages as read. Returns count marked."""
        msgs = self._messages.get(agent_id, [])
        count = 0
        for m in msgs:
            if msg_id is None or m.msg_id == msg_id:
                m.read = True
                count += 1
        return count

    def unread_count(self, agent_id: str) -> int:
        return sum(1 for m in self._messages.get(agent_id, []) if not m.read)

    def get_message_edges(self) -> list[tuple[str, str, int]]:
        """Return (from, to, count) pairs for graph edges."""
        counts: dict[tuple[str, str], int] = {}
        for to_agent, msgs in self._messages.items():
            for m in msgs:
                key = (m.from_agent, m.to_agent)
                counts[key] = counts.get(key, 0) + 1
        return [(f, t, c) for (f, t), c in counts.items()]
