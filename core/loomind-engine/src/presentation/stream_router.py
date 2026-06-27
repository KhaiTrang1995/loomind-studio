"""
Stream Router — GET /api/stream/{agent_id}

Server-Sent Events endpoint. Agents subscribe here to receive real-time
push notifications: task_assigned, task_available, goal_completed,
experience_evolved, heartbeat (every 25s to keep connection alive).

Phase 9D — Real-time Push.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stream"])

_HEARTBEAT_INTERVAL = 25.0  # seconds


@router.get("/stream/{agent_id}", response_class=StreamingResponse)
async def stream(agent_id: str, req: Request) -> StreamingResponse:
    """SSE stream for an agent. Keep connection open to receive push events."""
    event_bus = getattr(req.app.state, "event_bus", None)
    if event_bus is None:
        async def _unavailable():
            yield "data: {\"error\": \"event_bus not available\"}\n\n"
        return StreamingResponse(_unavailable(), media_type="text/event-stream")

    queue: asyncio.Queue = event_bus.subscribe(agent_id)

    async def generator():
        try:
            while True:
                if await req.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
                    data = json.dumps(event)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    hb = json.dumps({
                        "event": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    yield f"data: {hb}\n\n"
        finally:
            event_bus.unsubscribe(agent_id)
            logger.debug("SSE stream closed for agent %s", agent_id)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/fleet", response_class=StreamingResponse)
async def stream_fleet(req: Request) -> StreamingResponse:
    """SSE stream broadcasting fleet status + deliberation updates to the Fleet Monitor UI."""
    event_bus = getattr(req.app.state, "event_bus", None)
    cli_registry = getattr(req.app.state, "cli_registry", None)

    if event_bus is None:
        async def _unavailable():
            yield 'data: {"error": "event_bus not available"}\n\n'
        return StreamingResponse(_unavailable(), media_type="text/event-stream")

    queue: asyncio.Queue = event_bus.subscribe("fleet-monitor")

    # Push current fleet state immediately on connect, with task counts from goal store
    if cli_registry:
        goal_service = getattr(req.app.state, "goal_service", None)
        completed_counts: dict = {}
        if goal_service and goal_service.store:
            for goal in goal_service.store.list_goals():
                for task in goal.tasks:
                    if task.status == "completed" and task.assigned_to:
                        completed_counts[task.assigned_to] = completed_counts.get(task.assigned_to, 0) + 1
        fleet_data = []
        for r in cli_registry.get_fleet():
            d = r.model_dump(mode="json")
            d["tasks_completed"] = completed_counts.get(f"cli-{r.cli_type}", 0)
            fleet_data.append(d)
        initial = json.dumps({"event": "fleet_snapshot", "payload": fleet_data})
        async def generator_with_snapshot():
            yield f"data: {initial}\n\n"
            async for chunk in _fleet_generator(req, queue, event_bus):
                yield chunk
        return StreamingResponse(
            generator_with_snapshot(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        _fleet_generator(req, queue, event_bus),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _fleet_generator(req: Request, queue: asyncio.Queue, event_bus):
    try:
        while True:
            if await req.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
                # Forward deliberation_update and log events only
                evt_type = event.get("event", "")
                if evt_type in ("deliberation_update", "fleet_status", "log", "heartbeat"):
                    yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                hb = json.dumps({
                    "event": "heartbeat",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                yield f"data: {hb}\n\n"
    finally:
        event_bus.unsubscribe("fleet-monitor")
        logger.debug("Fleet SSE stream closed")
