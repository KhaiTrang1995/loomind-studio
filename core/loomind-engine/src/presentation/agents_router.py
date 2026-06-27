"""
Agents Router — Agent registry endpoints.

POST /api/agents/register  — register an agent with name, role, capabilities
POST /api/agents/heartbeat — refresh TTL
DELETE /api/agents/{id}    — deregister
GET  /api/agents           — list online agents

Phase 9B — Agent Identity.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from src.domain.models import AgentInfo, AgentRegisterRequest, AgentMessage, AgentSendMessageRequest, AgentGraph, AgentGraphNode, AgentGraphEdge, TaskRecord, TaskStatus, CLIStatus

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("/register", response_model=AgentInfo, status_code=201)
async def register(body: AgentRegisterRequest, req: Request) -> AgentInfo:
    """Register an agent with the engine. Idempotent — re-registration refreshes TTL."""
    registry = req.app.state.agent_registry
    return registry.register(body.agent_id, body.role, body.capabilities)


@router.post("/heartbeat")
async def heartbeat(req: Request, agent_id: str) -> dict:
    """Refresh an agent's TTL. Call every 60s to stay visible."""
    registry = req.app.state.agent_registry
    found = registry.heartbeat(agent_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not registered")
    return {"ok": True, "agent_id": agent_id}


@router.delete("/{agent_id}")
async def deregister(agent_id: str, req: Request) -> dict:
    """Remove an agent from the registry."""
    registry = req.app.state.agent_registry
    registry.deregister(agent_id)
    return {"ok": True, "agent_id": agent_id}


@router.get("", response_model=list[AgentInfo])
async def list_agents(req: Request) -> list[AgentInfo]:
    """Return all agents currently online (TTL not expired)."""
    return req.app.state.agent_registry.get_online()


@router.get("/graph", response_model=AgentGraph)
async def get_graph(req: Request) -> AgentGraph:
    """Return the current agent communication graph — nodes (agents + CLI fleet) and edges."""
    registry = req.app.state.agent_registry
    online = registry.get_online()

    nodes = [
        AgentGraphNode(
            id=a.agent_id,
            role=a.role.value,
            capabilities=a.capabilities,
            online=True,
            unread_count=registry.unread_count(a.agent_id),
        )
        for a in online
    ]

    # Add CLI fleet members as graph nodes
    cli_registry = getattr(req.app.state, "cli_registry", None)
    existing_ids = {n.id for n in nodes}
    if cli_registry:
        for rec in cli_registry.get_fleet():
            node_id = f"cli-{rec.cli_type}"
            if node_id not in existing_ids:
                nodes.append(AgentGraphNode(
                    id=node_id,
                    role=f"cli_{rec.cli_type}",
                    capabilities=[rec.cli_type, "headless", "autonomous"],
                    online=rec.status != "offline",
                    unread_count=0,
                ))

    # Always include ba-orchestrator as a virtual node representing the goal engine
    existing_ids = {n.id for n in nodes}
    if "ba-orchestrator" not in existing_ids:
        nodes.append(AgentGraphNode(
            id="ba-orchestrator",
            role="orchestrator",
            capabilities=["decompose", "assign", "evaluate"],
            online=True,
            unread_count=registry.unread_count("ba-orchestrator"),
        ))

    node_ids = {n.id for n in nodes}
    edges: list[AgentGraphEdge] = []

    # Message edges — show if at least one endpoint is a known node
    for from_agent, to_agent, count in registry.get_message_edges():
        if from_agent in node_ids or to_agent in node_ids:
            edges.append(AgentGraphEdge(
                source=from_agent,
                target=to_agent,
                type="message",
                label=f"{count} msg{'s' if count > 1 else ''}",
                message_count=count,
            ))

    # Goal edges — agents sharing the same goal
    goal_service = getattr(req.app.state, "goal_service", None)
    if goal_service:
        # Phase 11: GoalService uses SQLite via goal_store; Phase 9 used _goals dict
        goal_store = getattr(goal_service, "store", None)
        try:
            all_goals = goal_store.list_goals() if goal_store else []
        except Exception:
            all_goals = []
        for goal_record in all_goals:
            participants = list({t.assigned_to for t in goal_record.tasks if t.assigned_to})
            participants = [p for p in participants if p in node_ids]
            for i in range(len(participants)):
                for j in range(i + 1, len(participants)):
                    already = any(
                        (e.source == participants[i] and e.target == participants[j]) or
                        (e.source == participants[j] and e.target == participants[i])
                        for e in edges
                    )
                    if not already:
                        edges.append(AgentGraphEdge(
                            source=participants[i],
                            target=participants[j],
                            type="goal",
                            label=goal_record.goal[:30],
                        ))

    # Deliberation edges — CLIs that have participated in deliberations together
    deliberation_service = getattr(req.app.state, "deliberation_service", None)
    if deliberation_service:
        cli_node_ids = {n.id for n in nodes if n.role.startswith("cli_")}
        for d in deliberation_service.get_all()[:20]:
            initiator_id = f"cli-{d.initiator}"
            for participant in d.participants:
                participant_id = f"cli-{participant}"
                if initiator_id in cli_node_ids and participant_id in cli_node_ids:
                    already = any(
                        (e.source == initiator_id and e.target == participant_id) or
                        (e.source == participant_id and e.target == initiator_id)
                        for e in edges
                    )
                    if not already:
                        edges.append(AgentGraphEdge(
                            source=initiator_id,
                            target=participant_id,
                            type="message",
                            label="deliberate",
                            message_count=1,
                        ))

    return AgentGraph(nodes=nodes, edges=edges)


@router.post("/{agent_id}/messages", response_model=AgentMessage, status_code=201)
async def send_message(agent_id: str, body: AgentSendMessageRequest, req: Request) -> AgentMessage:
    """Send a message from one agent to another. Triggers SSE push to target."""
    registry = req.app.state.agent_registry
    msg = registry.send_message(
        from_agent=body.from_agent,
        to_agent=agent_id,
        content=body.content,
        context=body.context,
    )
    # Push SSE to target agent
    event_bus = getattr(req.app.state, "event_bus", None)
    if event_bus:
        event_bus.publish(agent_id, {
            "event": "agent_message",
            "payload": {
                "msg_id": msg.msg_id,
                "from_agent": msg.from_agent,
                "content": msg.content,
                "context": msg.context,
            },
        })
    return msg


@router.get("/{agent_id}/messages", response_model=list[AgentMessage])
async def get_messages(agent_id: str, req: Request, unread_only: bool = True) -> list[AgentMessage]:
    """Get messages for an agent. Set unread_only=false to get all messages."""
    registry = req.app.state.agent_registry
    msgs = registry.get_messages(agent_id, unread_only=unread_only)
    registry.mark_read(agent_id)
    return msgs


@router.get("/fleet", response_model=list)
async def get_fleet(req: Request) -> list:
    """Return current status of all CLI tools in the fleet, with persisted task counts."""
    cli_registry = getattr(req.app.state, "cli_registry", None)
    if cli_registry is None:
        return []

    # Compute tasks_completed per CLI from goal store (survives restarts)
    goal_service = getattr(req.app.state, "goal_service", None)
    completed_counts: dict[str, int] = {}
    if goal_service and goal_service.store:
        for goal in goal_service.store.list_goals():
            for task in goal.tasks:
                if task.status == "completed" and task.assigned_to:
                    completed_counts[task.assigned_to] = completed_counts.get(task.assigned_to, 0) + 1

    records = []
    for r in cli_registry.get_fleet():
        d = r.model_dump(mode="json")
        agent_key = f"cli-{r.cli_type}"
        d["tasks_completed"] = completed_counts.get(agent_key, 0)
        records.append(d)
    return records


class CLIStatusUpdate(BaseModel):
    status: str  # "online" | "busy" | "idle" | "offline"
    task: Optional[str] = None
    deliberation_id: Optional[str] = None
    pid: Optional[int] = None


@router.patch("/{agent_id}/status")
async def update_cli_status(agent_id: str, body: CLIStatusUpdate, req: Request) -> dict:
    """CLI hooks call this to report status changes. agent_id is the CLI type (claude, grok, ...)."""
    cli_registry = getattr(req.app.state, "cli_registry", None)
    event_bus = getattr(req.app.state, "event_bus", None)
    if cli_registry is None:
        return {"ok": True, "note": "cli_registry not available"}

    match body.status:
        case "online":
            cli_registry.set_online(agent_id)
        case "busy":
            cli_registry.set_busy(agent_id, task=body.task or "", deliberation_id=body.deliberation_id, pid=body.pid)
        case "idle":
            cli_registry.set_idle(agent_id)
        case "offline":
            cli_registry.set_offline(agent_id)

    # Broadcast fleet update with persisted task counts so Fleet Monitor stays accurate
    if event_bus:
        goal_service = getattr(req.app.state, "goal_service", None)
        completed_counts: dict = {}
        if goal_service and goal_service.store:
            for g in goal_service.store.list_goals():
                for t in g.tasks:
                    if t.status == "completed" and t.assigned_to:
                        completed_counts[t.assigned_to] = completed_counts.get(t.assigned_to, 0) + 1
        fleet = []
        for r in cli_registry.get_fleet():
            d = r.model_dump(mode="json")
            d["tasks_completed"] = completed_counts.get(f"cli-{r.cli_type}", 0)
            fleet.append(d)
        event_bus.broadcast({"event": "fleet_status", "payload": fleet})

    return {"ok": True, "cli": agent_id, "status": body.status}


@router.get("/fleet/pause")
async def get_fleet_pause(req: Request) -> dict:
    """Return whether the fleet is currently paused."""
    paused = getattr(req.app.state, "fleet_paused", False)
    return {"paused": paused}


@router.post("/fleet/pause")
async def pause_fleet(req: Request) -> dict:
    """Pause all agent-loop polling — agents stop picking up new tasks."""
    req.app.state.fleet_paused = True
    event_bus = getattr(req.app.state, "event_bus", None)
    if event_bus:
        event_bus.broadcast({"event": "fleet_paused", "payload": {"paused": True}})
    return {"paused": True}


@router.post("/fleet/resume")
async def resume_fleet(req: Request) -> dict:
    """Resume agent-loop polling after a pause."""
    req.app.state.fleet_paused = False
    event_bus = getattr(req.app.state, "event_bus", None)
    if event_bus:
        event_bus.broadcast({"event": "fleet_paused", "payload": {"paused": False}})
    return {"paused": False}


@router.get("/{agent_id}/tasks", response_model=list[TaskRecord])
async def get_agent_tasks(agent_id: str, req: Request) -> list[TaskRecord]:
    """Return tasks assigned to or available for this agent across all active goals."""
    if getattr(req.app.state, "fleet_paused", False):
        return []
    goal_service = getattr(req.app.state, "goal_service", None)
    if goal_service is None:
        return []
    tasks: list[TaskRecord] = []
    goal_store = getattr(goal_service, "store", None)
    try:
        all_goals = goal_store.list_goals() if goal_store else []
    except Exception:
        all_goals = []
    for record in all_goals:
        for task in record.tasks:
            if task.assigned_to == agent_id:
                tasks.append(task)
            elif task.assigned_to is None and task.status == TaskStatus.PENDING:
                tasks.append(task)
    return tasks
