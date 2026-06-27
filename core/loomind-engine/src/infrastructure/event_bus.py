"""
Event Bus — asyncio.Queue-based pub/sub for real-time agent notifications.

Agents subscribe by calling subscribe(agent_id), which returns an asyncio.Queue.
Publishers call publish(agent_id, event) or broadcast(event).
The SSE stream router consumes the queue and forwards events to agents.

Phase 9D — Real-time Push.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Events older than this are dropped from a subscriber's queue
_QUEUE_MAXSIZE = 128


class EventBus:
    """In-process async event bus. One queue per subscribed agent."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        """Return (or create) the event queue for an agent."""
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
            logger.debug("Agent subscribed to SSE stream: %s", agent_id)
        return self._queues[agent_id]

    def unsubscribe(self, agent_id: str) -> None:
        """Remove the agent's queue (called when SSE connection closes)."""
        self._queues.pop(agent_id, None)
        logger.debug("Agent unsubscribed from SSE stream: %s", agent_id)

    def publish(self, agent_id: str, event: dict) -> None:
        """Push an event to a specific agent's queue. Drops silently if queue is full."""
        queue = self._queues.get(agent_id)
        if queue is None:
            return
        event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("SSE queue full for agent %s; event dropped", agent_id)

    def broadcast(self, event: dict) -> None:
        """Push an event to all subscribed agents."""
        event.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        for agent_id in list(self._queues):
            self.publish(agent_id, event)

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)
