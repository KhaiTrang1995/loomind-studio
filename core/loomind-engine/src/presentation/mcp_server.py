import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

from src.config import settings
from src.domain.experience_service import ExperienceService
from src.infrastructure.embedder import Embedder
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.qdrant_client import QdrantStore

# HTTP client for registry/goal/posttool tools that need the running engine
_ENGINE_BASE_URL = os.environ.get("ENGINE_BASE_URL", "http://127.0.0.1:8082")
_http_client: httpx.AsyncClient | None = None


def get_http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(base_url=_ENGINE_BASE_URL, timeout=15.0)
    return _http_client

logger = logging.getLogger("loomind.mcp")

# Initialize FastMCP Server
mcp = FastMCP("Loomind Experience Engine")

# Lazy initialization backend components
_service = None
_qdrant = None
_embedder = None
_llm = None

def get_service() -> ExperienceService:
    global _service, _qdrant, _embedder, _llm
    if _service is None:
        logger.info("Initializing MCP backend components...")
        _qdrant = QdrantStore(
            mode=settings.qdrant_mode,
            path=settings.qdrant_path,
            url=settings.qdrant_url,
        )
        _embedder = Embedder(
            model_name=settings.embedding_model,
            device=settings.embedding_device,
        )
        llm_url = settings.ollama_url if settings.llm_provider == "ollama" else settings.llamacpp_url
        _llm = LLMClient(
            provider=settings.llm_provider,
            url=llm_url,
            model=settings.ollama_model,
        )
        _qdrant.ensure_collection(settings.qdrant_collection, _embedder.vector_size)
        _service = ExperienceService(
            qdrant=_qdrant,
            embedder=_embedder,
            llm=_llm,
            collection=settings.qdrant_collection,
        )
    return _service

@mcp.tool()
async def intercept_action(
    action: str,
    action_type: str = "unknown",
    file_path: str = "",
    language: str = ""
) -> str:
    """
    Intercept an action to check for matching team experience suggestions before executing it.

    Args:
        action: The description of the action to intercept (e.g. CLI command or code modification description).
        action_type: Type of action ('read', 'write', 'execute', 'unknown').
        file_path: Absolute or relative file path of the affected file.
        language: Programming language name (e.g. 'python', 'typescript').
    """
    from src.domain.models import InterceptRequest, ActionType

    try:
        act_type = ActionType(action_type.lower())
    except ValueError:
        act_type = ActionType.UNKNOWN

    req = InterceptRequest(
        action=action,
        action_type=act_type,
        file_path=file_path if file_path else None,
        language=language if language else None
    )

    service = get_service()
    res = await service.intercept(req)
    return res.model_dump_json(indent=2)

@mcp.tool()
def add_experience(
    title: str,
    description: str,
    category: str,
    severity: str = "info",
    tags: list[str] = None
) -> str:
    """
    Register a new coding experience or lesson learned into the Qdrant database.

    Args:
        title: Title of the experience pattern.
        description: Description of the mistake, fix, or guideline detail.
        category: Category of experience ('bug', 'pattern', 'security', 'performance').
        severity: Severity level ('info', 'warning', 'critical').
        tags: List of tags associated with this experience.
    """
    from src.domain.models import CreateExperienceRequest

    req = CreateExperienceRequest(
        title=title,
        description=description,
        category=category,
        severity=severity,
        tags=tags or []
    )

    service = get_service()
    exp = service.create_experience(req)
    return exp.model_dump_json(indent=2)

@mcp.tool()
def search_experiences(query: str, top_k: int = 5) -> str:
    """
    Search the experiences database semantically by a text query.

    Args:
        query: Semantic query text.
        top_k: Number of results to return.
    """
    service = get_service()
    exps = service.search_experiences(query, top_k=top_k)
    return json.dumps([e.model_dump(mode="json") for e in exps], indent=2)

@mcp.tool()
def get_stats() -> str:
    """
    Get Experience Engine usage statistics (total queries and average latency).
    """
    service = get_service()
    stats = {
        "total_queries": service.total_queries,
        "avg_latency_ms": service.avg_latency_ms
    }
    return json.dumps(stats, indent=2)

@mcp.tool()
async def get_health() -> str:
    """
    Get Experience Engine health status (Qdrant connection, LLM connection, and Embedder loading).
    """
    # Trigger lazy loading if not done
    get_service()
    is_qdrant_healthy = _qdrant.is_healthy(settings.qdrant_collection)
    is_llm_available = await _llm.is_available()

    health = {
        "status": "ok" if (is_qdrant_healthy and _embedder.is_loaded) else "degraded",
        "qdrant": is_qdrant_healthy,
        "embedder_loaded": _embedder.is_loaded,
        "llm_available": is_llm_available
    }
    return json.dumps(health, indent=2)

# ── Phase 9 — Harness Brain tools (call the running engine HTTP API) ──────────

@mcp.tool()
async def register_agent(agent_id: str, role: str = "general", capabilities: list[str] = None) -> str:
    """Register this agent with the Loomind engine on startup to enable task routing and SSE events.

    Args:
        agent_id: Unique identifier for this agent (e.g. 'coder-1').
        role: Agent role — 'orchestrator' | 'research' | 'coding' | 'testing' | 'evaluation' | 'general'.
        capabilities: List of capability tags (e.g. ['python', 'fastapi']).
    """
    http = get_http()
    resp = await http.post("/api/agents/register", json={
        "agent_id": agent_id,
        "role": role,
        "capabilities": capabilities or [],
    })
    return resp.text


@mcp.tool()
async def get_my_tasks(agent_id: str) -> str:
    """Get tasks assigned to this agent or available for claiming across all active goals.

    Args:
        agent_id: Your agent identifier (same as used in register_agent).
    """
    http = get_http()
    resp = await http.get(f"/api/agents/{agent_id}/tasks")
    return resp.text


@mcp.tool()
async def submit_goal(goal: str, submitted_by: str = "mcp-agent") -> str:
    """Submit a high-level goal. The engine decomposes it into research → code → test → evaluate tasks.

    Args:
        goal: Natural-language description of the goal (e.g. 'Build a REST API for user authentication').
        submitted_by: Identifier of the submitting agent or user.
    """
    http = get_http()
    resp = await http.post("/api/goals", json={"goal": goal, "submitted_by": submitted_by})
    return resp.text


@mcp.tool()
async def complete_task(goal_id: str, task_id: str, outcome: str, artifacts: dict = None) -> str:
    """Report task completion to the engine. Automatically triggers the next task in the pipeline.

    Args:
        goal_id: ID of the parent goal (from submit_goal response).
        task_id: ID of the task to complete (from get_my_tasks or SSE event).
        outcome: Summary of what was accomplished.
        artifacts: Optional dict of produced artifacts (file paths, test results, etc.).
    """
    http = get_http()
    resp = await http.post(
        f"/api/goals/{goal_id}/tasks/{task_id}/complete",
        json={"outcome": outcome, "artifacts": artifacts or {}},
    )
    return resp.text


@mcp.tool()
async def report_posttool(
    trace_id: str,
    suggestion_ids: list[str],
    action_taken: str,
    transcript_snippet: str = "",
) -> str:
    """Close the learning loop: report what you did with engine suggestions after acting.

    Args:
        trace_id: Trace ID from the intercept_action response.
        suggestion_ids: List of suggestion IDs from the intercept_action response.
        action_taken: How you used the suggestion — 'followed' | 'ignored' | 'modified'.
        transcript_snippet: Optional short excerpt of the relevant conversation or diff.
    """
    http = get_http()
    resp = await http.post("/api/posttool", json={
        "trace_id": trace_id,
        "suggestion_ids": suggestion_ids,
        "action_taken": action_taken,
        "transcript_snippet": transcript_snippet,
    })
    return resp.text


@mcp.tool()
async def send_agent_message(to_agent_id: str, content: str, context: str = "{}") -> str:
    """
    Send a message to another registered agent through the engine.

    Use this tool when you need information or coordination from a specific other agent,
    instead of asking the user. The target agent will receive the message via SSE
    and can reply with their own send_agent_message call.

    Args:
        to_agent_id: The agent_id of the target agent (must be registered and online).
        content: The message content — question, context, or instruction for the peer agent.
        context: Optional JSON string with structured context (e.g. '{"task_id": "...", "goal_id": "..."}').

    Returns:
        JSON with msg_id and status.
    """
    import json as _json
    http = get_http()
    try:
        ctx = _json.loads(context) if context and context.strip() not in ("{}", "") else {}
    except Exception:
        ctx = {}
    resp = await http.post(f"/api/agents/{to_agent_id}/messages", json={
        "from_agent": "mcp-agent",
        "content": content,
        "context": ctx,
    })
    if resp.status_code in (200, 201):
        data = resp.json()
        return f"Message sent. msg_id={data.get('msg_id', '?')}"
    return f"Failed to send message: HTTP {resp.status_code}"


@mcp.tool()
async def get_agent_messages(agent_id: str) -> str:
    """
    Get pending messages from other agents addressed to this agent.

    Call this at the start of each task to check if peer agents have sent you
    context, questions, or instructions. This replaces asking the user for
    information that another agent might already have.

    Args:
        agent_id: Your agent_id (must match how you registered).

    Returns:
        JSON array of unread messages. Empty array means no pending messages.
    """
    import json as _json
    http = get_http()
    resp = await http.get(f"/api/agents/{agent_id}/messages", params={"unread_only": "true"})
    if resp.status_code == 200:
        msgs = resp.json()
        if not msgs:
            return "No pending messages."
        return _json.dumps(msgs, indent=2, default=str)
    return f"Failed to get messages: HTTP {resp.status_code}"


# ── Phase 11 — Agentic Brain tools ───────────────────────────────────────────

@mcp.tool()
async def analyze_goal(goal: str, submitted_by: str = "mcp-agent") -> str:
    """
    Analyze a goal with the BA Agent: decompose it into User Stories, Acceptance Criteria,
    and Fibonacci story points. Returns a GoalRecord with all tasks queued and prioritized.
    Use this INSTEAD of submit_goal when you want intelligent BA-level decomposition.

    Args:
        goal: Natural-language goal description (in any language).
        submitted_by: Identifier of the requesting agent or SA.
    """
    http = get_http()
    resp = await http.post("/api/ba/analyze", json={"goal": goal, "submitted_by": submitted_by})
    return resp.text


@mcp.tool()
async def approve_hitl_task(goal_id: str, task_id: str, approved: bool, comment: str = "") -> str:
    """
    Approve or reject a HITL (Human-in-the-Loop) task.
    SECURITY tasks and DELETE operations always require explicit approval — never auto-escalate.
    Non-security HITL tasks auto-execute after 180 seconds if no approval is given.

    Args:
        goal_id: The parent goal ID.
        task_id: The task ID awaiting approval (status must be HITL_PENDING).
        approved: True to approve and proceed, False to send back to queue.
        comment: Optional justification for the approval/rejection decision.
    """
    http = get_http()
    resp = await http.post(
        f"/api/ba/goals/{goal_id}/tasks/{task_id}/approve",
        json={"approved": approved, "comment": comment},
    )
    return resp.text


@mcp.tool()
async def save_task_checkpoint(goal_id: str, task_id: str, checkpoint: str) -> str:
    """
    Save a checkpoint for an in-progress task to enable resume-on-interrupt.
    Call this periodically during long tasks so work can resume from this point
    if interrupted — without restarting and wasting tokens.

    Args:
        goal_id: The parent goal ID.
        task_id: The task ID currently in progress.
        checkpoint: Serialized progress state (JSON string or plain description).
    """
    http = get_http()
    resp = await http.post(
        f"/api/ba/goals/{goal_id}/tasks/{task_id}/checkpoint",
        json={"checkpoint": checkpoint},
    )
    return resp.text


@mcp.tool()
async def toggle_notifications(enabled: bool) -> str:
    """
    Toggle the notification feature flag ON or OFF.
    When ON, progress updates are sent to configured webhooks/Telegram.
    Feature is OFF by default — only enable when webhooks are configured.

    Args:
        enabled: True to enable notifications, False to disable.
    """
    http = get_http()
    resp = await http.post("/api/ba/notifications/toggle", json={"enabled": enabled})
    return resp.text


@mcp.tool()
async def set_webhook(url: str, remove: bool = False) -> str:
    """
    Add or remove a webhook URL for progress notifications.
    Each webhook receives POST requests with JSON: {"text": "<message>"}.
    Multiple webhooks are supported. Feature flag must be ON to send notifications.

    Args:
        url: The webhook URL to add or remove.
        remove: Set True to remove the URL instead of adding it.
    """
    http = get_http()
    # Get current config
    config_resp = await http.get("/api/ba/notifications/config")
    if config_resp.status_code != 200:
        return f"Failed to get config: HTTP {config_resp.status_code}"

    config = config_resp.json()
    urls: list[str] = config.get("webhook_urls", [])

    if remove:
        urls = [u for u in urls if u != url]
    elif url not in urls:
        urls.append(url)

    patch_resp = await http.patch("/api/ba/notifications/config", json={"webhook_urls": urls})
    return patch_resp.text


if __name__ == "__main__":
    import sys
    # Suppress normal logging output on stdout to prevent protocol disruption
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    mcp.run(transport="stdio")
