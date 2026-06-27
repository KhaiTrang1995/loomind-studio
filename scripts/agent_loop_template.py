"""
Agent Loop Template — 3-Agent Orchestrated Demo

Demonstrates the Phase 3 Orchestrated Loop from docs/Agent-loop.jpg:

  Orchestrator submits Goal
       ↓
  Engine decomposes → [research, code, test, evaluate]
       ↓
  Research Agent  claims & completes research task
       ↓  (SSE: task_available → coding)
  Coding Agent    claims & completes code task
       ↓  (SSE: task_available → testing)
  Testing Agent   claims & completes test task
       ↓  (SSE: task_available → evaluate — claimed by orchestrator)
  Orchestrator    marks evaluate done → goal_completed broadcast

Usage:
    cd core/loomind-engine
    python ../../scripts/agent_loop_template.py

Engine must be running at http://127.0.0.1:8082.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import os

# Allow running from the scripts/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core", "loomind-engine"))

from src.client import LoomindClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("agent_loop_demo")

ENGINE_URL = os.environ.get("ENGINE_URL", "http://127.0.0.1:8082")
GOAL = os.environ.get("AGENT_GOAL", "Build a REST API endpoint for user authentication with JWT tokens")


# ── Agent executors ────────────────────────────────────────────────────────────

async def research_executor(task: dict) -> str:
    logger.info("[research] Executing: %s", task.get("description"))
    await asyncio.sleep(1)  # Simulate work
    return "Found 3 relevant patterns: JWT best practices, FastAPI auth middleware, token refresh flow."


async def coding_executor(task: dict) -> str:
    logger.info("[coding] Executing: %s", task.get("description"))
    await asyncio.sleep(2)  # Simulate work
    return "Implemented POST /auth/login and POST /auth/refresh with HS256 JWT. 142 lines written."


async def testing_executor(task: dict) -> str:
    logger.info("[testing] Executing: %s", task.get("description"))
    await asyncio.sleep(1)  # Simulate work
    return "8 tests written, 8 passed. Coverage: 94%. Edge cases: expired token, wrong password."


async def evaluation_executor(task: dict) -> str:
    logger.info("[evaluation] Executing: %s", task.get("description"))
    await asyncio.sleep(1)  # Simulate work
    return "LGTM. Security review passed. No hardcoded secrets. Rate limiting applied."


# ── Agent runners ─────────────────────────────────────────────────────────────

async def run_agent(
    agent_id: str,
    role: str,
    capabilities: list[str],
    executor,
    stop_event: asyncio.Event,
) -> None:
    client = LoomindClient(base_url=ENGINE_URL)
    try:
        await client.aregister(agent_id, role, capabilities)
        logger.info("[%s] Registered. Waiting for tasks…", agent_id)

        async def _heartbeat():
            while not stop_event.is_set():
                await asyncio.sleep(60)
                try:
                    await client.aheartbeat(agent_id)
                except Exception:
                    pass

        hb = asyncio.create_task(_heartbeat())
        try:
            async for event in client.asubscribe(agent_id):
                if stop_event.is_set():
                    break
                evt_type = event.get("event")
                if evt_type == "heartbeat":
                    continue
                if evt_type == "goal_completed":
                    logger.info("[%s] Goal completed: %s", agent_id, event.get("payload", {}).get("goal"))
                    stop_event.set()
                    break
                if evt_type in ("task_assigned", "task_available"):
                    payload = event.get("payload", {})
                    goal_id = payload.get("goal_id")
                    task_id = payload.get("task_id")
                    task_type = payload.get("task_type")
                    # Only handle tasks matching our role
                    if task_type != role and role != "orchestrator":
                        continue
                    try:
                        task = await client.aclaim_task(goal_id, task_id, agent_id)
                    except Exception:
                        continue  # Another agent was faster
                    # Intercept before acting
                    intercept_resp = await client.aintercept(
                        action=task.get("description", ""),
                        action_type="write",
                    )
                    trace_id = intercept_resp.get("trace_id", "")
                    suggestion_ids = [s["experience_id"] for s in intercept_resp.get("suggestions", [])]
                    if suggestion_ids:
                        logger.info("[%s] Got %d suggestion(s) from engine.", agent_id, len(suggestion_ids))
                    # Run the work
                    outcome = await executor(task)
                    # PostTool — feed result back to the learning loop
                    if trace_id and suggestion_ids:
                        await client.aposttool(trace_id, suggestion_ids, "followed")
                    # Report done
                    await client.acomplete_task(goal_id, task_id, outcome)
                    logger.info("[%s] Task '%s' done.", agent_id, task_type)
        finally:
            hb.cancel()
    finally:
        client.close()


# ── Orchestrator ───────────────────────────────────────────────────────────────

async def run_orchestrator(stop_event: asyncio.Event) -> None:
    client = LoomindClient(base_url=ENGINE_URL)
    try:
        await client.aregister("orchestrator-1", "orchestrator", ["goal-submission", "evaluation"])
        logger.info("[orchestrator] Registered.")

        # Submit the goal
        record = await client.asubmit_goal(GOAL, submitted_by="orchestrator-1")
        goal_id = record["goal_id"]
        logger.info("[orchestrator] Goal submitted: %s  (%d tasks)", goal_id, len(record.get("tasks", [])))

        # Handle evaluation task when it arrives
        async def _heartbeat():
            while not stop_event.is_set():
                await asyncio.sleep(60)
                try:
                    await client.aheartbeat("orchestrator-1")
                except Exception:
                    pass

        hb = asyncio.create_task(_heartbeat())
        try:
            async for event in client.asubscribe("orchestrator-1"):
                if stop_event.is_set():
                    break
                evt_type = event.get("event")
                if evt_type == "heartbeat":
                    continue
                if evt_type == "goal_completed":
                    logger.info("[orchestrator] All tasks done. Loop complete!")
                    stop_event.set()
                    break
                if evt_type in ("task_assigned", "task_available"):
                    payload = event.get("payload", {})
                    if payload.get("task_type") != "evaluate":
                        continue
                    task_id = payload.get("task_id")
                    try:
                        task = await client.aclaim_task(goal_id, task_id, "orchestrator-1")
                    except Exception:
                        continue
                    outcome = await evaluation_executor(task)
                    await client.acomplete_task(goal_id, task_id, outcome)
                    logger.info("[orchestrator] Evaluation done. Waiting for goal_completed…")
        finally:
            hb.cancel()
    finally:
        client.close()


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    # Verify engine is up
    probe = LoomindClient(base_url=ENGINE_URL)
    if not probe.is_healthy():
        logger.error("Engine not reachable at %s — start it first.", ENGINE_URL)
        probe.close()
        sys.exit(1)
    probe.close()

    logger.info("=== Loomind Agent Loop Demo ===")
    logger.info("Goal: %s", GOAL)
    logger.info("Engine: %s", ENGINE_URL)

    stop_event = asyncio.Event()

    # Run all agents concurrently; orchestrator also submits the goal
    await asyncio.gather(
        run_orchestrator(stop_event),
        run_agent("researcher-1", "research",   ["web-search", "rag"],       research_executor, stop_event),
        run_agent("coder-1",      "coding",     ["python", "fastapi"],        coding_executor,   stop_event),
        run_agent("tester-1",     "testing",    ["pytest", "coverage"],       testing_executor,  stop_event),
        return_exceptions=True,
    )

    logger.info("=== Demo complete ===")


if __name__ == "__main__":
    asyncio.run(main())
