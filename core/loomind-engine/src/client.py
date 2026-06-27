import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Dict, Any, List, Optional

import httpx

logger = logging.getLogger("loomind.client")


class LoomindClient:
    """
    Python client SDK for interacting with the Loomind Experience Engine.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8082", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(timeout=self.timeout)
        self._async_client: Optional[httpx.AsyncClient] = None

    def close(self):
        self.client.close()
        if self._async_client and not self._async_client.is_closed:
            asyncio.get_event_loop().run_until_complete(self._async_client.aclose())

    def _get_async(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._async_client

    # ── Sync methods (backward-compatible) ────────────────────────────────

    def is_healthy(self) -> bool:
        """Check if the experience engine is running and healthy."""
        try:
            resp = self.client.get(f"{self.base_url}/health")
            return resp.status_code == 200 and resp.json().get("status") == "ok"
        except Exception:
            return False

    def intercept(
        self,
        action: str,
        action_type: str = "unknown",
        file_path: Optional[str] = None,
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send an action to the intercept pipeline and get suggestions.
        """
        payload = {
            "action": action,
            "action_type": action_type,
            "file_path": file_path,
            "language": language
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            resp = self.client.post(f"{self.base_url}/api/intercept", json=payload)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.error("Failed to intercept. Server returned status: %d", resp.status_code)
                return {"skipped": False, "suggestions": [], "latency_ms": 0.0, "layers_executed": ["client-fallback"]}
        except Exception as e:
            logger.error("Failed to connect to Experience Engine: %s", e)
            return {"skipped": False, "suggestions": [], "latency_ms": 0.0, "layers_executed": ["client-offline"]}

    def add_experience(
        self,
        title: str,
        description: str,
        category: str,
        severity: str = "info",
        tags: List[str] = None
    ) -> Dict[str, Any]:
        """
        Add a new experience to the database.
        """
        payload = {
            "title": title,
            "description": description,
            "category": category,
            "severity": severity,
            "tags": tags or []
        }
        resp = self.client.post(f"{self.base_url}/api/experiences", json=payload)
        resp.raise_for_status()
        return resp.json()

    def search_experiences(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Semantically search experiences.
        """
        payload = {"query": query, "top_k": top_k}
        resp = self.client.post(f"{self.base_url}/api/experiences/search", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Async methods (Phase 9F) ───────────────────────────────────────────

    async def aregister(self, agent_id: str, role: str = "general", capabilities: List[str] = None) -> Dict[str, Any]:
        """Register this agent with the engine. Call once on startup."""
        ac = self._get_async()
        resp = await ac.post("/api/agents/register", json={
            "agent_id": agent_id,
            "role": role,
            "capabilities": capabilities or [],
        })
        resp.raise_for_status()
        return resp.json()

    async def aheartbeat(self, agent_id: str) -> None:
        """Refresh agent TTL. Call every 60s to stay visible."""
        ac = self._get_async()
        await ac.post("/api/agents/heartbeat", params={"agent_id": agent_id})

    async def aintercept(self, action: str, action_type: str = "unknown", file_path: Optional[str] = None, language: Optional[str] = None) -> Dict[str, Any]:
        """Async intercept — returns suggestions before acting."""
        ac = self._get_async()
        payload = {"action": action, "action_type": action_type}
        if file_path:
            payload["file_path"] = file_path
        if language:
            payload["language"] = language
        try:
            resp = await ac.post("/api/intercept", json=payload)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {"skipped": False, "suggestions": [], "latency_ms": 0.0, "layers_executed": ["client-offline"]}

    async def aposttool(self, trace_id: str, suggestion_ids: List[str], action_taken: str, transcript_snippet: str = "") -> Dict[str, Any]:
        """Close the learning loop after acting. action_taken: 'followed'|'ignored'|'modified'."""
        ac = self._get_async()
        resp = await ac.post("/api/posttool", json={
            "trace_id": trace_id,
            "suggestion_ids": suggestion_ids,
            "action_taken": action_taken,
            "transcript_snippet": transcript_snippet,
        })
        resp.raise_for_status()
        return resp.json()

    async def asubmit_goal(self, goal: str, submitted_by: str = "agent") -> Dict[str, Any]:
        """Submit a goal and receive the decomposed task list."""
        ac = self._get_async()
        resp = await ac.post("/api/goals", json={"goal": goal, "submitted_by": submitted_by})
        resp.raise_for_status()
        return resp.json()

    async def aclaim_task(self, goal_id: str, task_id: str, agent_id: str) -> Dict[str, Any]:
        """Claim a pending task. Returns 409 if already taken."""
        ac = self._get_async()
        resp = await ac.post(f"/api/goals/{goal_id}/tasks/{task_id}/claim", json={"agent_id": agent_id})
        resp.raise_for_status()
        return resp.json()

    async def acomplete_task(self, goal_id: str, task_id: str, outcome: str, artifacts: Dict = None) -> Dict[str, Any]:
        """Report task completion."""
        ac = self._get_async()
        resp = await ac.post(f"/api/goals/{goal_id}/tasks/{task_id}/complete", json={
            "outcome": outcome,
            "artifacts": artifacts or {},
        })
        resp.raise_for_status()
        return resp.json()

    async def asubscribe(self, agent_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to SSE events for this agent. Yields parsed event dicts."""
        ac = self._get_async()
        async with ac.stream("GET", f"/api/stream/{agent_id}") as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    if raw:
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            pass

    async def asend_message(self, to_agent_id: str, content: str, from_agent: str, context: dict | None = None) -> dict:
        """Send a message to another agent."""
        http = self._get_async()
        resp = await http.post(f"/api/agents/{to_agent_id}/messages", json={
            "from_agent": from_agent,
            "content": content,
            "context": context or {},
        })
        if resp.status_code in (200, 201):
            return resp.json()
        return {}

    async def aget_messages(self, agent_id: str, unread_only: bool = True) -> list[dict]:
        """Get messages addressed to this agent."""
        http = self._get_async()
        resp = await http.get(f"/api/agents/{agent_id}/messages", params={"unread_only": str(unread_only).lower()})
        if resp.status_code == 200:
            return resp.json()
        return []

    async def agent_loop(
        self,
        agent_id: str,
        role: str,
        capabilities: List[str],
        executor: Callable[[Dict[str, Any]], Any],
        *,
        heartbeat_interval: float = 60.0,
    ) -> None:
        """
        Standard agent loop:
          1. Register with engine
          2. Subscribe to SSE stream
          3. On task_assigned: intercept → execute → aposttool → complete
          4. Heartbeat every heartbeat_interval seconds in background
        """
        await self.aregister(agent_id, role, capabilities)
        logger.info("[%s] Registered as '%s'. Listening for tasks…", agent_id, role)

        async def _heartbeat():
            while True:
                await asyncio.sleep(heartbeat_interval)
                try:
                    await self.aheartbeat(agent_id)
                except Exception:
                    pass

        hb_task = asyncio.create_task(_heartbeat(), name=f"{agent_id}-heartbeat")
        try:
            async for event in self.asubscribe(agent_id):
                evt_type = event.get("event")
                if evt_type == "agent_message":
                    payload = event.get("payload", {})
                    logger.info(
                        "[%s] Received agent_message from %s: %s",
                        agent_id,
                        payload.get("from_agent", "unknown"),
                        payload.get("content", ""),
                    )
                    try:
                        await executor({"event": "agent_message", **payload})
                    except Exception as exc:
                        logger.warning("[%s] executor error on agent_message: %s", agent_id, exc)
                elif evt_type in ("task_assigned", "task_available"):
                    payload = event.get("payload", {})
                    goal_id = payload.get("goal_id")
                    task_id = payload.get("task_id")
                    if not goal_id or not task_id:
                        continue
                    try:
                        task = await self.aclaim_task(goal_id, task_id, agent_id)
                    except Exception:
                        continue  # Already claimed by another agent
                    intercept_resp = await self.aintercept(
                        action=task.get("description", ""),
                        action_type="write",
                    )
                    trace_id = intercept_resp.get("trace_id", "")
                    suggestion_ids = [s["experience_id"] for s in intercept_resp.get("suggestions", [])]
                    try:
                        outcome = await executor(task)
                        action_taken = "followed" if suggestion_ids else "ignored"
                    except Exception as exc:
                        outcome = f"Error: {exc}"
                        action_taken = "ignored"
                    if trace_id and suggestion_ids:
                        await self.aposttool(trace_id, suggestion_ids, action_taken)
                    await self.acomplete_task(goal_id, task_id, str(outcome))
                    logger.info("[%s] Task %s completed.", agent_id, task_id)
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass


# ==================== LangChain & CrewAI Adapters ====================

try:
    from langchain_core.callbacks import BaseCallbackHandler

    class LoomindLangChainCallback(BaseCallbackHandler):
        """
        LangChain callback handler to automatically intercept agent tools/actions.
        """
        def __init__(self, client: LoomindClient):
            self.client = client

        def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> Any:
            """Run when tool starts running."""
            tool_name = serialized.get("name", "unknown_tool")
            action_desc = f"Run tool {tool_name} with input: {input_str}"

            res = self.client.intercept(
                action=action_desc,
                action_type="execute"
            )

            if not res.get("skipped", False) and res.get("suggestions"):
                print("\n[Loomind Experience Engine Suggestions]")
                for sugg in res["suggestions"]:
                    print(f"  - [{sugg['severity'].upper()}] {sugg['title']}: {sugg['message']}")
                print("")
except ImportError:
    pass

try:
    from crewai.tools import tool

    def create_loomind_crewai_tool(client: LoomindClient):
        """
        Create a CrewAI tool for querying experiences.
        """
        @tool("Query Experience Engine")
        def query_experience_engine(action_description: str) -> str:
            """
            Query the Experience Engine to check if there are any historical warnings
            or guidelines for the planned action.
            """
            res = client.intercept(action=action_description)
            if res.get("skipped", False):
                return "Action is read-only. No guidelines needed."
            suggestions = res.get("suggestions", [])
            if not suggestions:
                return "No matching warnings or suggestions in database."

            out = []
            for s in suggestions:
                out.append(f"[{s['severity'].upper()}] {s['title']}: {s['message']}")
            return "\n".join(out)

        return query_experience_engine
except ImportError:
    pass
