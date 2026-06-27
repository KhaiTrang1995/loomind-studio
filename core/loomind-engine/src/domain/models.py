"""
Domain Models for Loomind Experience Engine.
All request/response schemas using Pydantic v2.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ==================== Enums ====================


class ActionType(str, Enum):
    """Classification of an AI agent action."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    """Severity level for experiences and suggestions."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class KnowledgeTier(str, Enum):
    """4-Tier knowledge architecture classification.

    - T0_PRINCIPLE: always-loaded, generalized rules abstracted from clusters
    - T1_BEHAVIORAL: always-loaded, confirmed reflexes
    - T2_QA_CACHE: retrieved on semantic match (default tier for v1 creates)
    - T3_RAW: staging tier, TTL 30 days, may be noisy
    """

    T0_PRINCIPLE = "t0_principle"
    T1_BEHAVIORAL = "t1_behavioral"
    T2_QA_CACHE = "t2_qa_cache"
    T3_RAW = "t3_raw"


class EdgeType(str, Enum):
    """Type of relation between two experiences in the graph."""

    GENERALIZES = "generalizes"  # T0 ─generalizes→ T1 member
    RELATES_TO = "relates_to"    # symmetric, weight ∈ [0,1]
    SUPERSEDES = "supersedes"    # newer ─supersedes→ older


# ==================== Core Models ====================


# ==================== Graph Models ====================


class Edge(BaseModel):
    """A typed directional link between two experiences in the knowledge graph."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    src_id: str = Field(..., description="Source experience ID")
    dst_id: str = Field(..., description="Destination experience ID")
    type: EdgeType = Field(..., description="Edge type: generalizes, relates_to, supersedes")
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Edge weight 0.0–1.0")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==================== Request/Response Models ====================


class InterceptRequest(BaseModel):
    """Request from the Extension when an Agent is about to perform an action."""

    action: str = Field(..., description="Description of the action (e.g., 'edit file db.ts')")
    action_type: ActionType = Field(default=ActionType.UNKNOWN, description="Classified action type")
    file_path: Optional[str] = Field(default=None, description="File being operated on")
    file_content: Optional[str] = Field(default=None, description="File content snippet for context")
    language: Optional[str] = Field(default=None, description="Programming language")
    agent: Optional[str] = Field(default=None, description="AI agent name (copilot, cursor)")
    context: Optional[str] = Field(default=None, description="Additional context")


class Suggestion(BaseModel):
    """A suggestion returned to the Extension for injection into the Agent prompt."""

    experience_id: str = Field(..., description="ID of the source experience")
    title: str = Field(..., description="Short title")
    message: str = Field(..., description="Full suggestion message")
    severity: Severity = Field(default=Severity.INFO)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Relevance 0.0–1.0")
    source: str = Field(default="semantic_search", description="How this was sourced")


class InterceptResponse(BaseModel):
    """Response returned to the Extension after processing an intercept request."""

    skipped: bool = Field(..., description="True if Layer 1 skipped (read-only action)")
    suggestions: list[Suggestion] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, description="Total processing time in ms")
    layers_executed: list[str] = Field(default_factory=list, description="Which layers ran")


# ==================== Experience ====================


class Experience(BaseModel):
    """A stored experience / lesson learned."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    category: str = Field(default="pattern", description="Category: bug, pattern, security, performance")
    tags: list[str] = Field(default_factory=list)
    file_patterns: list[str] = Field(default_factory=list, description="e.g., ['*.ts', 'db.*']")
    language: Optional[str] = None
    severity: Severity = Field(default=Severity.INFO)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    usage_count: int = Field(default=0, description="Number of times suggested")
    feedback_score: float = Field(default=0.0, description="Feedback -1.0 to 1.0")

    # ── v2 fields (additive, all defaulted for backward compatibility) ──
    tier: KnowledgeTier = Field(
        default=KnowledgeTier.T2_QA_CACHE,
        description="Knowledge tier classification (defaults to T2 for v1 creates).",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score 0.0–1.0; used by ranker and promotion thresholds.",
    )
    superseded_by: Optional[str] = Field(
        default=None,
        description="ID of newer experience that replaces this one; if non-null, excluded from intercept results.",
    )
    followed_count: int = Field(
        default=0,
        ge=0,
        description="Number of FOLLOWED verdicts recorded for this experience.",
    )
    ignored_count: int = Field(
        default=0,
        ge=0,
        description="Number of IGNORED or IRRELEVANT verdicts recorded for this experience.",
    )
    last_used_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the most recent intercept that surfaced this experience.",
    )


class CreateExperienceRequest(BaseModel):
    """Request to create a new experience."""

    title: str
    description: str
    category: str = "pattern"
    tags: list[str] = Field(default_factory=list)
    file_patterns: list[str] = Field(default_factory=list)
    language: Optional[str] = None
    severity: Severity = Field(default=Severity.INFO)


class UpdateExperienceRequest(BaseModel):
    """Request to update an existing experience."""

    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    file_patterns: Optional[list[str]] = None
    severity: Optional[Severity] = None


class FeedbackRequest(BaseModel):
    """Feedback for an experience suggestion."""

    score: float = Field(..., ge=-1.0, le=1.0, description="Score from -1.0 (bad) to 1.0 (good)")
    comment: Optional[str] = None


# ==================== Health ====================


class HealthStatus(BaseModel):
    """Engine health status."""

    status: str = "ok"
    engine: str = "running"
    qdrant: bool = False
    embedder_loaded: bool = False
    llm_available: bool = False
    uptime_seconds: float = 0.0
    version: str = "0.1.0"


class EngineStats(BaseModel):
    """Engine statistics."""

    total_experiences: int = 0
    total_queries: int = 0
    avg_latency_ms: float = 0.0
    cache_hit_rate: float = 0.0
    queries_today: int = 0


class PaginatedResponse(BaseModel):
    """Paginated response wrapper."""

    items: list[Experience] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


# ==================== Observation & Judge Models ====================


class Observation(BaseModel):
    """A judge verdict for a single experience suggestion.

    Records whether the agent FOLLOWED, IGNORED, or found the suggestion IRRELEVANT/UNCLEAR.
    Used by the evolution engine to promote/demote experiences across tiers.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    experience_id: str = Field(..., description="ID of the experience that was suggested")
    session_id: str = Field(..., description="Session in which the observation was made")
    verdict: Literal["FOLLOWED", "IGNORED", "IRRELEVANT", "UNCLEAR"] = Field(
        ..., description="Judge verdict for this suggestion"
    )
    rationale: str = Field(..., description="LLM-generated rationale for the verdict")
    judged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    judge_model: str = Field(..., description="Model used for judging (e.g., 'llama3')")
    processed_by_evolution: bool = Field(
        default=False, description="True after evolution cycle has consumed this observation"
    )


# ==================== Principle Model ====================


class Principle(Experience):
    """T0 entry. Aggregates ≥3 T1 members into a generalized rule.

    Inherits all Experience fields and adds member tracking and abstraction summary.
    """

    member_ids: list[str] = Field(
        ..., description="IDs of T1 experiences that were abstracted into this principle"
    )
    abstraction_summary: str = Field(
        ..., description="LLM-generated summary explaining the generalized principle"
    )


# ==================== Timeline Model ====================


class TimelineEntry(BaseModel):
    """A single entry in the reverse-chronological supersession timeline."""

    experience_id: str = Field(..., description="ID of the experience")
    title: str = Field(..., description="Experience title")
    summary: str = Field(..., description="Brief summary of the experience")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    superseded: bool = Field(..., description="Whether this entry has been superseded")
    superseded_by: Optional[str] = Field(
        default=None, description="ID of the experience that supersedes this one"
    )
    created_at: datetime = Field(..., description="When this experience was created")


# ==================== PostTool Models ====================


class PostToolRequest(BaseModel):
    """Request sent after a tool use to provide closed-loop learning signal.

    Links back to the intercept via trace_id so the judge can evaluate
    whether the agent followed or ignored the suggestions.
    """

    trace_id: str = Field(..., description="Trace ID returned by /api/intercept v2")
    suggestion_ids: list[str] = Field(
        ..., description="IDs of suggestions that were shown to the agent"
    )
    action_taken: str = Field(..., description="What the agent actually did")
    file_path: Optional[str] = Field(default=None, description="File that was modified")
    outcome: Literal["success", "failure", "unknown"] = Field(
        default="unknown", description="Outcome of the action"
    )
    transcript_snippet: Optional[str] = Field(
        default=None, description="Last ~500 tokens of transcript for judge context"
    )


class PostToolAck(BaseModel):
    """Acknowledgment returned after enqueuing a posttool request for judging."""

    accepted: bool = Field(..., description="Whether the request was accepted for processing")
    queued_at: datetime = Field(..., description="When the item was enqueued")
    job_id: str = Field(..., description="Unique job ID for tracking")


# ==================== Intercept v2 Response ====================


class InterceptResponseV2(InterceptResponse):
    """Extended intercept response with trace linkage and enrichment metadata.

    Backward-compatible: all new fields are optional or have defaults.
    V1 clients can ignore the new fields safely.
    """

    trace_id: str = Field(..., description="Unique trace ID for linking with /api/posttool")
    intent: Optional[str] = Field(
        default=None, description="Detected intent (plan, generate, refactor, debug, docs, analyze)"
    )
    enriched_action: Optional[str] = Field(
        default=None, description="PIL-enriched action string used for embedding"
    )
    tier_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Count of suggestions per tier (e.g., {'t0_principle': 1, 't2_qa_cache': 2})",
    )


# ==================== Import/Export ====================


class ExportBundle(BaseModel):
    """Complete export of all experiences for backup/migration."""

    version: str = "1.0"
    engine_version: str = "0.1.0"
    exported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total: int = 0
    experiences: list[dict] = Field(default_factory=list)


class ImportRequest(BaseModel):
    """Request to import experiences from a backup file."""

    experiences: list[dict] = Field(..., description="List of experience objects to import")
    overwrite: bool = Field(default=False, description="Overwrite existing experiences with same ID")


class ImportResult(BaseModel):
    """Result of an import operation."""

    imported: int = 0
    skipped: int = 0
    failed: int = 0
    total_in_file: int = 0


# ==================== Evolution Report ====================


class EvolutionReport(BaseModel):
    """Result of one evolution cycle."""

    promoted_t3_to_t2: int = 0
    promoted_t2_to_t1: int = 0
    abstracted_t1_to_t0: int = 0
    principle_ids: list[str] = Field(default_factory=list)
    demoted_t1_to_t2: int = 0
    demoted_t2_to_t3: int = 0
    pruned_t3_expired: int = 0
    observations_consumed: int = 0
    duration_ms: float = 0.0


# ==================== Routing Models ====================


class TaskTier(str, Enum):
    """Model routing tier classification."""

    HOT = "hot"    # leader / deep reasoning
    WARM = "warm"  # implement / fast cheap
    COLD = "cold"  # research / docs (cheapest)


class RoutingDecision(BaseModel):
    """Result of model routing."""

    tier: TaskTier
    model: str
    reasoning_effort: Literal["low", "medium", "high"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: Literal["keyword", "history", "brain"]
    fallback_chain: list[str] = Field(default_factory=list)


class TaskRoute(BaseModel):
    """Higher-level workflow routing plan."""

    workflow: Literal["single", "council", "research_first"]
    rounds: int = 1
    models: list[str] = Field(default_factory=list)
    auto_triggered: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ==================== Extract Models ====================


class ExtractResult(BaseModel):
    """Result of session transcript extraction."""

    created: int = 0
    deduped: int = 0
    lesson_ids: list[str] = Field(default_factory=list)


# ==================== Gates / Status ====================


class GatesStatus(BaseModel):
    """System readiness status for /api/gates."""

    qdrant_ok: bool = False
    embedder_loaded: bool = False
    llm_available: bool = False
    judge_worker: Literal["running", "stopped", "error"] = "stopped"
    evolve_cron: Literal["running", "stopped", "error"] = "stopped"
    tiers: dict[str, int] = Field(default_factory=dict)
    queue_depth: dict[str, int] = Field(default_factory=dict)


# ==================== Shared Principle Bundle ====================


class SharedPrincipleBundle(BaseModel):
    """Exportable/importable principle bundle for cross-project sharing."""

    version: str = "1.0"
    principle: dict = Field(..., description="Serialized Experience (T0 Principle)")
    member_summaries: list[dict] = Field(
        default_factory=list,
        description="List of {id, title} for up to 50 member experiences",
    )
    signature: Optional[str] = Field(
        default=None,
        description="HMAC-SHA256 signature for verification (optional)",
    )


# ==================== Judge Models ====================


class JudgeItem(BaseModel):
    """A single item queued for judge evaluation."""

    trace_id: str
    suggestion_id: str
    action_taken: str
    transcript_snippet: Optional[str] = None


# ==================== Agent Registry Models (Phase 9B) ====================


class AgentRole(str, Enum):
    """Role classification for registered agents."""

    ORCHESTRATOR = "orchestrator"
    RESEARCH = "research"
    CODING = "coding"
    TESTING = "testing"
    EVALUATION = "evaluation"
    GENERAL = "general"


class AgentInfo(BaseModel):
    """A registered agent's identity and capabilities."""

    agent_id: str = Field(..., description="Unique agent identifier")
    role: AgentRole = Field(default=AgentRole.GENERAL)
    capabilities: list[str] = Field(default_factory=list, description="e.g. ['python', 'fastapi']")
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRegisterRequest(BaseModel):
    """Request to register an agent with the engine."""

    agent_id: str
    role: AgentRole = AgentRole.GENERAL
    capabilities: list[str] = Field(default_factory=list)


# ==================== Goal / Task Models (Phase 9C) ====================


class TaskStatus(str, Enum):
    PENDING = "pending"
    HITL_PENDING = "hitl_pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    INTERRUPTED = "interrupted"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskRecord(BaseModel):
    """A single task within a goal, assigned to one agent role."""

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal_id: str
    task_type: str = Field(..., description="research | code | test | evaluate")
    description: str
    assigned_to: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    mode: str = "auto"
    story_points: int = 1
    retry_count: int = 0
    checkpoint: Optional[str] = None
    hitl_deadline: Optional[datetime] = None
    outcome: Optional[str] = None
    artifacts: dict = Field(default_factory=dict)
    # Agents that exhausted MAX_RETRIES — blocked from re-claiming until HITL manual reset
    failed_by: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


class GoalRecord(BaseModel):
    """A high-level goal decomposed into typed tasks for the agent team."""

    goal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    submitted_by: str
    tasks: list[TaskRecord] = Field(default_factory=list)
    status: str = "pending"
    analysis: Optional[dict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    worktree_id: Optional[str] = None
    worktree_path: Optional[str] = None  # denormalized host path for agent_loop


class GoalSubmitRequest(BaseModel):
    """Request to submit a new goal."""

    goal: str
    submitted_by: str = "anonymous"
    worktree_id: Optional[str] = None


# ==================== Worktree Models ====================


class WorktreeRecord(BaseModel):
    """A registered repository workspace for scoped task execution."""

    worktree_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    path: str  # absolute path on the host machine
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = True


class WorktreeCreateRequest(BaseModel):
    name: str
    path: str
    description: str = ""


class WorktreePatchRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    active: Optional[bool] = None


class TaskClaimRequest(BaseModel):
    """Request by an agent to claim a task."""

    agent_id: str


class TaskCompleteRequest(BaseModel):
    """Request by an agent to report task completion."""

    outcome: str
    artifacts: dict = Field(default_factory=dict)


# ==================== Agent Messaging (Phase 10) ====================

class AgentMessage(BaseModel):
    msg_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_agent: str
    to_agent: str
    content: str
    context: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    read: bool = False

class AgentSendMessageRequest(BaseModel):
    from_agent: str
    content: str
    context: dict = Field(default_factory=dict)

# ==================== Agent Graph (Phase 10) ====================

class AgentGraphNode(BaseModel):
    id: str
    role: str
    capabilities: list[str]
    online: bool
    unread_count: int = 0

class AgentGraphEdge(BaseModel):
    source: str
    target: str
    type: str  # "message" | "goal"
    label: str = ""
    message_count: int = 0

class AgentGraph(BaseModel):
    nodes: list[AgentGraphNode]
    edges: list[AgentGraphEdge]


# ==================== Multi-CLI Fleet Models (Phase 12) ====================


class CLIType(str, Enum):
    CLAUDE = "claude"
    GROK = "grok"
    CODEX = "codex"
    AGY = "agy"


class CLIStatus(str, Enum):
    ONLINE = "online"   # registered, idle
    BUSY = "busy"       # executing a task or deliberation round
    IDLE = "idle"       # was busy, now free
    OFFLINE = "offline" # not registered / not found on PATH


class CLIStatusRecord(BaseModel):
    cli_type: CLIType
    status: CLIStatus = CLIStatus.OFFLINE
    current_task: Optional[str] = None
    current_deliberation_id: Optional[str] = None
    pid: Optional[int] = None
    tasks_completed: int = 0
    last_seen: Optional[datetime] = None


class DeliberationVote(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    COUNTER_PROPOSE = "counter_propose"
    NEED_HUMAN = "need_human"
    ABSTAIN = "abstain"


class DeliberationStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    HITL_PENDING = "hitl_pending"
    CANCELLED = "cancelled"


class DeliberationRound(BaseModel):
    round_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent: str
    proposal: str
    vote: DeliberationVote = DeliberationVote.ABSTAIN
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Deliberation(BaseModel):
    deliberation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    context: str = ""
    initiator: str
    participants: list[str] = Field(default_factory=list)
    rounds: list[DeliberationRound] = Field(default_factory=list)
    status: DeliberationStatus = DeliberationStatus.OPEN
    consensus: Optional[str] = None
    max_rounds: int = 3
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None


class ConsultRequest(BaseModel):
    """Request from a CLI to start a multi-agent deliberation."""
    from_cli: str
    topic: str
    context: str = ""
    urgency: Literal["low", "medium", "high"] = "medium"
    preferred_consultants: list[str] = Field(default_factory=list)


class ConsultResponse(BaseModel):
    deliberation_id: str
    status: DeliberationStatus
    consensus: Optional[str] = None
    rounds_so_far: int = 0


class HITLResolveRequest(BaseModel):
    approved: bool
    consensus: str = ""


# ==================== Agentic Brain — BA Agent Models (Phase 11) ====================

FIBONACCI_POINTS = (1, 2, 3, 5, 8, 13)


class TaskMode(str, Enum):
    AUTO = "auto"
    HITL = "hitl"
    SECURITY = "security"


class AcceptanceCriteria(BaseModel):
    given: str
    when: str
    then: str


class UserStory(BaseModel):
    story_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str
    acceptance_criteria: list[AcceptanceCriteria] = Field(default_factory=list)
    story_points: int = Field(default=1, description="Fibonacci: 1,2,3,5,8,13")
    task_mode: TaskMode = TaskMode.AUTO
    task_type: str = "code"


class BAAnalysisResult(BaseModel):
    goal_id: str
    goal: str
    user_stories: list[UserStory]
    total_points: int
    analysis_notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BAAnalyzeRequest(BaseModel):
    goal: str
    submitted_by: str = "anonymous"
    language: str = "vi"
    worktree_id: Optional[str] = None


class HITLApproveRequest(BaseModel):
    approved: bool
    comment: str = ""


class NotificationConfig(BaseModel):
    enabled: bool = False
    webhook_urls: list[str] = Field(default_factory=list)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


class NotificationConfigUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    webhook_urls: Optional[list[str]] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
