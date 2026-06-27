"""
Loomind Experience Engine — FastAPI Application Entrypoint

v0.3: Full continual-learning brain with:
- v2 intercept pipeline (PIL → multi-tier → graph → rank → LLM filter)
- Closed-loop learning (posttool → judge → evolve)
- Experience graph + temporal reasoning
- Model routing
- Principle sharing
- Security (redaction, auth, rate limiting)
- System readiness (gates)

Phase 11 — Agentic Brain (BA Agent, HITL, SQLite persistence, notifications)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.domain.experience_service import ExperienceService
from src.domain.graph.graph_service import GraphService
from src.domain.pil.pil_enricher import PILEnricher
from src.infrastructure.embedder import Embedder
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.qdrant_client import QdrantStore

# Presentation routers
from src.presentation.experience_router import router as experience_router
from src.presentation.health_router import router as health_router
from src.presentation.intercept_router import router as intercept_router
from src.presentation.posttool_router import router as posttool_router
from src.presentation.extract_router import router as extract_router
from src.presentation.evolve_router import router as evolve_router
from src.presentation.graph_router import router as graph_router
from src.presentation.timeline_router import router as timeline_router
from src.presentation.route_router import router as route_router
from src.presentation.principles_router import router as principles_router
from src.presentation.gates_router import router as gates_router
from src.presentation.agents_router import router as agents_router
from src.presentation.goals_router import router as goals_router
from src.presentation.stream_router import router as stream_router
from src.presentation.ba_router import router as ba_router
from src.presentation.config_router import router as config_router
from src.presentation.deliberation_router import router as deliberation_router
from src.presentation.worktrees_router import router as worktrees_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.engine_log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("loomind")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize and tear down services."""
    logger.info("=" * 60)
    logger.info("Loomind Experience Engine v0.3 starting...")
    logger.info("=" * 60)

    # Initialize infrastructure
    logger.info("Initializing Qdrant (%s mode)...", settings.qdrant_mode)
    qdrant = QdrantStore(
        mode=settings.qdrant_mode,
        path=settings.qdrant_path,
        url=settings.qdrant_url,
    )

    logger.info("Initializing Embedder (%s)...", settings.embedding_model)
    embedder = Embedder(
        model_name=settings.embedding_model,
        device=settings.embedding_device,
    )

    logger.info("Initializing LLM Client (%s — %s)...", settings.llm_provider, settings.ollama_model)
    llm_url = settings.ollama_url if settings.llm_provider == "ollama" else settings.llamacpp_url
    llm = LLMClient(
        provider=settings.llm_provider,
        url=llm_url,
        model=settings.ollama_model,
    )

    # Ensure Qdrant collections
    qdrant.ensure_collection(settings.qdrant_collection, embedder.vector_size)
    logger.info("Ensuring tier collections exist...")
    qdrant.ensure_tier_collections(vector_size=embedder.vector_size)
    logger.info("Tier collections ready.")

    # Initialize domain services
    pil = PILEnricher()
    graph_service = GraphService(qdrant=qdrant, embedder=embedder)

    # Wire up the main service
    service = ExperienceService(
        qdrant=qdrant,
        embedder=embedder,
        llm=llm,
        collection=settings.qdrant_collection,
        pil=pil,
        graph=graph_service,
    )
    app.state.service = service
    app.state.graph_service = graph_service

    # Initialize evolution services
    from src.domain.evolution.judge_service import JudgeService
    from src.domain.evolution.evolution_service import EvolutionService
    from src.domain.evolution.extraction_service import ExtractionService
    from src.domain.routing.router_service import RouterService
    from src.infrastructure.rate_limiter import RateLimiter

    judge_service = JudgeService(llm=llm, store=qdrant)
    evolution_service = EvolutionService(store=qdrant, embedder=embedder, llm=llm, graph=graph_service)
    extraction_service = ExtractionService(store=qdrant, embedder=embedder, llm=llm)
    router_service = RouterService(llm=llm)
    rate_limiter = RateLimiter(max_requests=settings.extract_rate_limit)

    app.state.extraction_service = extraction_service
    app.state.router_service = router_service
    app.state.evolution_service = evolution_service
    app.state.rate_limiter = rate_limiter
    app.state.intercept_rate_limiter = RateLimiter(max_requests=settings.intercept_rate_limit)

    # Phase 9 — Harness Brain: observations collection + agent registry + event bus + goal service
    qdrant.ensure_observations_collection()
    logger.info("Observations collection ready.")

    from src.infrastructure.agent_registry import AgentRegistry
    from src.infrastructure.event_bus import EventBus
    from src.domain.orchestration.goal_service import GoalService

    agent_registry = AgentRegistry()
    event_bus = EventBus()

    # Wire log broadcasting — all engine log records forwarded to SSE subscribers
    from src.infrastructure.log_broadcaster import setup_log_broadcasting, teardown_log_broadcasting
    setup_log_broadcasting(event_bus)

    # Phase 11 — Agentic Brain: SQLite goal store, BA Agent, notification service
    from src.infrastructure.goal_store import GoalStore
    from src.domain.ba_agent.ba_service import BAService
    from src.infrastructure.notification_service import NotificationService
    from src.domain.models import NotificationConfig

    goal_store = GoalStore(db_path=settings.goal_db_path)
    ba_service = BAService(llm=llm)

    notification_config = NotificationConfig(
        enabled=settings.notification_enabled,
        telegram_bot_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
    )
    notification_service = NotificationService(config=notification_config)

    goal_service = GoalService(
        event_bus=event_bus,
        agent_registry=agent_registry,
        goal_store=goal_store,
        ba_service=ba_service,
        notification_service=notification_service,
        experience_service=service,
        hitl_timeout_seconds=settings.hitl_timeout_seconds,
    )

    app.state.agent_registry = agent_registry
    app.state.event_bus = event_bus
    app.state.goal_service = goal_service
    app.state.notification_service = notification_service
    app.state.fleet_paused = False  # UI pause toggle — POST /api/agents/fleet/pause to set
    logger.info("Agent registry, event bus, goal service (Phase 11 Agentic Brain) initialized.")

    # Worktree registry — multi-repo task execution
    from src.infrastructure.worktree_store import WorktreeStore
    worktree_store = WorktreeStore(path=str(Path(settings.goal_db_path).parent / "worktrees.json"))
    app.state.worktree_store = worktree_store
    logger.info("Worktree store initialized (%d repos registered).", len(worktree_store.list_all()))

    # Phase 12 — Multi-CLI Fleet: CLI executor, registry, deliberation service
    from src.infrastructure.cli_executor import CLIExecutor
    from src.infrastructure.cli_registry import CLIRegistry
    from src.domain.deliberation.deliberation_service import DeliberationService

    cli_registry = CLIRegistry()
    cli_executor = CLIExecutor(event_bus=event_bus, default_timeout=settings.cli_timeout_seconds)
    deliberation_service = DeliberationService(
        executor=cli_executor,
        cli_registry=cli_registry,
        event_bus=event_bus,
        max_rounds=settings.deliberation_max_rounds,
        cli_timeout=settings.cli_timeout_seconds,
        experience_service=service,
    )

    app.state.cli_registry = cli_registry
    app.state.cli_executor = cli_executor
    app.state.deliberation_service = deliberation_service
    logger.info("CLIExecutor + CLIRegistry + DeliberationService (Phase 12 Multi-CLI Fleet) initialized.")

    # Start background worker
    worker = None
    if settings.enable_judge_worker:
        from src.infrastructure.background_worker import BackgroundWorker
        worker = BackgroundWorker(
            judge_service=judge_service,
            evolution_service=evolution_service,
            batch_interval=settings.judge_batch_interval,
            batch_size=settings.judge_batch_size,
            evolve_interval_minutes=settings.evolve_interval_minutes,
            qdrant=qdrant,
        )
        await worker.start()
        logger.info("BackgroundWorker started")

    app.state.worker = worker

    logger.info("Engine ready at http://%s:%d", settings.engine_host, settings.engine_port)
    logger.info("OpenAPI docs at http://%s:%d/docs", settings.engine_host, settings.engine_port)

    yield

    # Shutdown
    logger.info("Shutting down...")
    teardown_log_broadcasting()
    if worker:
        await worker.stop()
    await notification_service.aclose()
    qdrant.close()
    await llm.close()
    logger.info("Goodbye!")


# ==================== App Factory ====================

app = FastAPI(
    title="Loomind Experience Engine",
    description="AI Experience Engine v0.3 — Agentic Brain with BA decomposition, HITL, and autonomous goal loop",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS — allow extension and desktop app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware (only active when AUTH_SECRET_KEY is set)
if settings.auth_secret_key:
    from src.infrastructure.auth_middleware import AuthMiddleware
    app.add_middleware(AuthMiddleware, secret_key=settings.auth_secret_key)

# Register routers — v1 (unchanged paths)
app.include_router(intercept_router)
app.include_router(experience_router)
app.include_router(health_router)

# Register routers — v2 (new endpoints)
app.include_router(posttool_router)
app.include_router(extract_router)
app.include_router(evolve_router)
app.include_router(graph_router)
app.include_router(timeline_router)
app.include_router(route_router)
app.include_router(principles_router)
app.include_router(gates_router)

# Register routers — Phase 9 (Harness Brain)
app.include_router(agents_router)
app.include_router(goals_router)
app.include_router(stream_router)

# Register routers — Phase 11 (Agentic Brain — BA Agent, HITL, notifications)
app.include_router(ba_router)
app.include_router(config_router)

# Register routers — Phase 12 (Multi-CLI Fleet + Deliberation)
app.include_router(deliberation_router)

# Register routers — Worktrees (multi-repo task execution)
app.include_router(worktrees_router)


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "name": "Loomind Experience Engine",
        "version": "0.3.0",
        "docs": "/docs",
        "health": "/health",
        "gates": "/api/gates",
        "agentic_brain": "/api/ba/analyze",
    }


# ==================== CLI Entrypoint ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.engine_host,
        port=settings.engine_port,
        reload=True,
        log_level=settings.engine_log_level,
    )
