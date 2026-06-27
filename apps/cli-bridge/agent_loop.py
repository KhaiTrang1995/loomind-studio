"""
Agent Loop Runner — autonomous CLI task consumer for Loomind Fleet.

Runs on HOST alongside CLI Bridge. Each available CLI polls the engine
for tasks, executes them headlessly via the bridge, reports outcomes back.

Flow:
  Engine: POST /api/goals  →  BA decomposes  →  tasks queued
  Loop:   poll tasks  →  claim  →  prompt CLI via bridge  →  complete
          detect DELIBERATE:  →  auto-trigger /api/deliberate
          detect EXPERIENCE:  →  auto-save /api/experiences

Startup: registers each CLI as an agent in engine (role matches task_type).
Heartbeat: every 60s to keep registrations alive.

Usage:
    python agent_loop.py [--engine http://localhost:8082] [--bridge http://localhost:8083]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | agent_loop | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent_loop")

# ── Config ────────────────────────────────────────────────────────────────────
# Env vars are fallbacks; startup fetches live values from bridge GET /config.

ENGINE_URL         = os.getenv("ENGINE_URL",  "http://localhost:8082")
BRIDGE_URL         = os.getenv("BRIDGE_URL",  "http://localhost:8083")
POLL_INTERVAL      = int(os.getenv("POLL_INTERVAL",      "15"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
CLI_TIMEOUT        = int(os.getenv("CLI_TIMEOUT",        "120"))
MAX_ITERATIONS     = int(os.getenv("MAX_ITERATIONS",     "3"))

# CLI → role mapping (matches AgentRole enum + task_type routing)
CLI_ROLES: dict[str, str] = {
    "claude": "coding",
    "grok":   "research",
    "codex":  "testing",
    "agy":    "evaluation",
}

# Which task_types each CLI prefers (ordered — first = most preferred)
# Used as baseline; _AffinityTracker overrides with live success-rate data.
CLI_TASK_AFFINITY: dict[str, list[str]] = {
    "claude": ["code",     "evaluate", "research", "test"],
    "grok":   ["research", "evaluate", "code",     "test"],
    "codex":  ["test",     "code",     "research", "evaluate"],
    "agy":    ["evaluate", "research", "code",     "test"],
}

# ── Item 4: Dynamic CLI-to-task affinity tracker ──────────────────────────────

_AFFINITY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cli_affinity.json")


class _AffinityTracker:
    """Persists per-CLI success/failure counts per task_type; returns dynamic ordering.

    Laplace-smoothed score = (ok + 1) / (ok + fail + 2) so new task types start
    at 0.5 and move toward 1 or 0 with observed data. When no data exists yet for
    a CLI, falls back to the static CLI_TASK_AFFINITY baseline.
    """

    def __init__(self, path: str = _AFFINITY_PATH) -> None:
        self._path = path
        # {cli: {task_type: {"ok": int, "fail": int}}}
        self._data: dict[str, dict[str, dict[str, int]]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path) as f:
                self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.debug("Affinity save failed: %s", e)

    def record(self, cli: str, task_type: str, *, success: bool) -> None:
        cli_stats = self._data.setdefault(cli, {})
        tt_stats  = cli_stats.setdefault(task_type, {"ok": 0, "fail": 0})
        tt_stats["ok" if success else "fail"] += 1
        self._save()
        logger.debug(
            "Affinity updated: %s/%s ok=%d fail=%d",
            cli, task_type, tt_stats["ok"], tt_stats["fail"],
        )

    def order(self, cli: str) -> list[str]:
        """Return task types sorted by live success rate, falling back to static baseline."""
        baseline = CLI_TASK_AFFINITY.get(cli, ["code", "research", "test", "evaluate"])
        stats = self._data.get(cli, {})
        if not stats:
            return baseline
        # Union of known types (baseline + observed) — new types inherit 0.5 prior
        all_types = list(dict.fromkeys(baseline + list(stats.keys())))

        def score(tt: str) -> float:
            s = stats.get(tt, {})
            ok, fail = s.get("ok", 0), s.get("fail", 0)
            return (ok + 1) / (ok + fail + 2)

        return sorted(all_types, key=score, reverse=True)

    def stats_summary(self, cli: str) -> str:
        """One-line summary for log output."""
        stats = self._data.get(cli, {})
        if not stats:
            return "no data"
        parts = [
            f"{tt}:{s.get('ok', 0)}ok/{s.get('fail', 0)}fail"
            for tt, s in stats.items()
        ]
        return " ".join(parts)


_affinity = _AffinityTracker()

# Per-task-type instructions — tells CLI exactly what kind of work to do
_TASK_INSTRUCTIONS: dict[str, str] = {
    "research": (
        "RESEARCH TASK: Analyze the topic deeply. Identify key constraints, "
        "existing solutions, trade-offs, and relevant prior art. "
        "Produce a structured findings report with clear recommendations."
    ),
    "code": (
        "CODING TASK: Write production-quality code. Include error handling. "
        "Reference prior research findings. If implementing a design decision, "
        "explain the approach briefly before the code."
    ),
    "test": (
        "TESTING TASK: Write comprehensive tests covering happy path, edge cases, "
        "and error conditions. Reference the code implementation from prior tasks. "
        "Include test descriptions explaining what each test verifies."
    ),
    "evaluate": (
        "EVALUATION TASK: Review the work done in prior tasks critically. "
        "Check correctness, completeness, security, and alignment with the goal. "
        "Give a structured verdict: PASS / NEEDS_REVISION with specific findings."
    ),
}

TASK_PROMPT_TEMPLATE = """\
You are {cli_name} in the Loomind Multi-CLI Fleet — an autonomous AI agent.

GOAL: {goal}
TASK TYPE: {task_type}
YOUR TASK: {description}

{task_instructions}

RELEVANT TEAM KNOWLEDGE (from experience base):
{intercept_suggestions}

CONTEXT FROM PRIOR TASKS IN THIS GOAL:
{prior_context}

INSTRUCTIONS:
1. Complete this task thoroughly and concisely.
2. If you need another agent's perspective on a key decision, write on its own line:
   DELIBERATE: <your question or topic>
3. If you learn something worth saving as team knowledge, write on its own line:
   EXPERIENCE: <one-line insight>
4. End your response with exactly this JSON on the very last line (no trailing text):
   {{"status":"completed","confidence":0.8,"summary":"one-line summary","key_output":"main result or decision"}}

Begin your response now.
"""


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(method: str, url: str, body: Optional[dict] = None, timeout: int = 10) -> Optional[dict]:
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        logger.warning("%s %s → HTTP %d: %s", method, url, e.code, e.read().decode()[:120])
    except Exception as e:
        logger.debug("%s %s failed: %s", method, url, e)
    return None


def get(path: str, base: str = ENGINE_URL) -> Optional[dict]:
    return _req("GET", f"{base}{path}")


def post(path: str, body: dict, base: str = ENGINE_URL, timeout: int = 10) -> Optional[dict]:
    return _req("POST", f"{base}{path}", body, timeout=timeout)


def patch(path: str, body: dict, base: str = ENGINE_URL) -> Optional[dict]:
    return _req("PATCH", f"{base}{path}", body)


# ── Bridge check ──────────────────────────────────────────────────────────────

def get_available_clis() -> list[str]:
    health = get("/health", base=BRIDGE_URL)
    if not health:
        logger.error("CLI Bridge not reachable at %s", BRIDGE_URL)
        return []
    available = health.get("available_clis", {})
    found = [cli for cli, ok in available.items() if ok]
    logger.info("Available CLIs via bridge: %s", found)
    return found


# ── Agent registration ────────────────────────────────────────────────────────

def register_cli_as_agent(cli: str) -> bool:
    agent_id = f"cli-{cli}"
    role = CLI_ROLES.get(cli, "general")
    result = post("/api/agents/register", {
        "agent_id": agent_id,
        "role": role,
        "capabilities": [cli, "headless", "autonomous", role],
    })
    if result:
        logger.info("Registered %s as agent '%s' (role=%s)", cli, agent_id, role)
        return True
    return False


def heartbeat(cli: str) -> None:
    post(f"/api/agents/heartbeat?agent_id=cli-{cli}", {})


# ── Task helpers ──────────────────────────────────────────────────────────────

def get_available_tasks(cli: str) -> list[dict]:
    """Return pending tasks for this CLI sorted by live affinity score then story_points DESC."""
    result = get(f"/api/agents/cli-{cli}/tasks")
    if not isinstance(result, list):
        return []
    affinity = _affinity.order(cli)
    def sort_key(t: dict) -> tuple:
        tt = t.get("task_type", "")
        pref = affinity.index(tt) if tt in affinity else len(affinity)
        return (pref, -t.get("story_points", 1))
    return sorted(result, key=sort_key)


def claim_task(goal_id: str, task_id: str, cli: str) -> bool:
    result = post(f"/api/goals/{goal_id}/tasks/{task_id}/claim", {"agent_id": f"cli-{cli}"})
    return result is not None


def complete_task(goal_id: str, task_id: str, outcome: str, artifacts: dict) -> bool:
    result = post(f"/api/goals/{goal_id}/tasks/{task_id}/complete", {
        "outcome": outcome,
        "artifacts": artifacts,
    })
    return result is not None


def fail_task(goal_id: str, task_id: str, reason: str) -> None:
    post(f"/api/goals/{goal_id}/tasks/{task_id}/fail", {"outcome": reason})


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _count_lines(text: str) -> int:
    return len([l for l in text.split("\n") if l.strip()])


def _extract_files(text: str) -> list[str]:
    """Extract file paths mentioned in CLI output."""
    hits = re.findall(r"\b[\w./\\-]+\.(?:py|ts|tsx|js|rs|go|java|sh|yaml|yml|json|md|toml|cfg|env)\b", text)
    # Deduplicate, keep only plausible relative paths (not pure names like 'README.md')
    seen: dict[str, bool] = {}
    result = []
    for h in hits:
        h = h.replace("\\", "/")
        if h not in seen and ("/" in h or len(h) > 8):
            seen[h] = True
            result.append(h)
            if len(result) >= 15:
                break
    return result


def intercept_task(description: str, task_type: str) -> tuple[str, str, list[str]]:
    """Call engine intercept pipeline.

    Returns (suggestions_text, trace_id, suggestion_ids).
    trace_id + suggestion_ids are used later to close the learning loop via /api/posttool.
    """
    result = post("/api/intercept", {
        "action": description,
        "action_type": "write" if task_type in ("code", "test") else "read",
        "context": f"task_type={task_type}",
    })
    if not result:
        return "No prior knowledge found.", "", []
    trace_id: str = result.get("trace_id", "")
    suggestions = result.get("suggestions", [])
    suggestion_ids: list[str] = [
        s["experience_id"] for s in suggestions if s.get("experience_id")
    ]
    if not suggestions:
        return "No relevant experiences in knowledge base yet.", trace_id, []
    lines = []
    for s in suggestions[:3]:
        title = s.get("title", "")
        desc = s.get("description", "")[:150]
        conf = s.get("confidence", 0)
        lines.append(f"- [{conf:.0%}] {title}: {desc}")
    return "\n".join(lines), trace_id, suggestion_ids


def report_posttool(trace_id: str, suggestion_ids: list[str], action_taken: str, transcript: str = "") -> None:
    """Close the learning loop — tell the engine whether the surfaced knowledge helped."""
    if not trace_id or not suggestion_ids:
        return  # nothing to report (no suggestions were surfaced)
    result = post("/api/posttool", {
        "trace_id": trace_id,
        "suggestion_ids": suggestion_ids,
        "action_taken": action_taken,
        "transcript_snippet": transcript[:400],
    })
    if result:
        logger.debug("PostTool reported: trace=%s action=%s", trace_id[:8], action_taken[:40])


def get_prior_context(goal_id: str) -> str:
    """Build structured working memory from completed tasks in this goal.

    Allocates more budget to code/research key_output since test and evaluate
    tasks depend on them most. Total budget ≈ 1600 chars.
    """
    tasks = get(f"/api/goals/{goal_id}/tasks")
    if not isinstance(tasks, list):
        return "No prior context."

    _BUDGET: dict[str, int] = {
        "research": 400,
        "code":     600,
        "test":     300,
        "evaluate": 200,
    }
    _DEFAULT_BUDGET = 200

    sections: list[str] = []
    revision_notes: list[str] = []

    for t in tasks:
        if t.get("status") != "completed":
            continue
        tt     = t.get("task_type", "general")
        budget = _BUDGET.get(tt, _DEFAULT_BUDGET)
        arts   = t.get("artifacts") or {}

        # Prefer key_output from artifacts (richer), fall back to outcome summary
        key_out = str(arts.get("key_output") or "")
        outcome = str(t.get("outcome") or "")
        body    = key_out if len(key_out) > len(outcome) else outcome
        body    = body[:budget]

        files = arts.get("files_mentioned") or []
        file_note = f"  files: {', '.join(files[:5])}" if files else ""
        conf = arts.get("confidence")
        conf_note = f"  conf={conf:.2f}" if isinstance(conf, float) else ""

        sections.append(f"[{tt}]{conf_note}\n{body}{file_note}")

        # Item 8: collect evaluate NEEDS_REVISION verdicts for the revision hint section
        if tt == "evaluate":
            verdict_upper = outcome.upper()
            if any(kw in verdict_upper for kw in (
                "NEEDS_REVISION", "NEEDS REVISION", "FAIL", "NOT_READY", "REWORK",
            )):
                revision_notes.append(outcome[:300])

    # Item 8: prepend a prominent revision hint so the agent knows exactly what to fix
    header = ""
    if revision_notes:
        joined = "\n---\n".join(revision_notes)
        header = (
            f"[REVISION REQUIRED — previous evaluate(s) flagged these issues. "
            f"Address them before completing your task]\n{joined}\n\n"
        )

    body_text = "\n\n".join(sections) if sections else "No prior tasks completed yet."
    return header + body_text


# ── Output parsing ────────────────────────────────────────────────────────────

@dataclass
class CLIOutput:
    raw: str
    summary: str = ""
    confidence: float = 0.7
    key_output: str = ""
    deliberate_topics: list[str] = field(default_factory=list)
    experiences: list[str] = field(default_factory=list)


def parse_output(raw: str) -> CLIOutput:
    out = CLIOutput(raw=raw)
    lines = raw.strip().split("\n")

    # Extract DELIBERATE: and EXPERIENCE: annotations
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r"DELIBERATE:\s*(.+)", stripped, re.IGNORECASE)
        if m:
            out.deliberate_topics.append(m.group(1).strip())
            continue
        m = re.match(r"EXPERIENCE:\s*(.+)", stripped, re.IGNORECASE)
        if m:
            out.experiences.append(m.group(1).strip())
            continue
        clean_lines.append(line)

    # Try JSON on last non-empty line
    for line in reversed(clean_lines):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                out.summary    = str(data.get("summary",    ""))
                out.confidence = float(data.get("confidence", 0.7))
                out.key_output = str(data.get("key_output", ""))
                return out
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

    # Fallback: use last 3 lines as summary
    non_empty = [l.strip() for l in clean_lines if l.strip()]
    out.summary = " ".join(non_empty[-3:]) if non_empty else raw[:200]
    out.key_output = out.summary
    return out


# ── Side effects: deliberate & experience ────────────────────────────────────

def trigger_deliberation(cli: str, topic: str, goal_context: str) -> None:
    result = post("/api/deliberate", {
        "from_cli": cli,
        "topic": topic,
        "context": goal_context[:500],
        "preferred_consultants": [c for c in CLI_ROLES if c != cli],
    })
    if result:
        logger.info("[%s] Deliberation triggered: %s → %s", cli, topic[:60], result.get("deliberation_id", "?"))


def save_experience(cli: str, insight: str, task_type: str, extra_tags: list[str] | None = None) -> None:
    tags = [cli, task_type, "autonomous", "agent-loop"] + (extra_tags or [])
    result = post("/api/experiences", {
        "title": f"[{cli}] {insight[:60]}",
        "description": insight,
        "category": "agent-loop",
        "tags": tags,
    })
    if result:
        logger.info("[%s] Experience saved: %s", cli, insight[:60])


def vote_experience(exp_id: str, vote: str) -> None:
    """Direct quality signal — upvote or downvote a surfaced experience based on evaluate verdict."""
    post(f"/api/experiences/{exp_id}/feedback", {"vote": vote})


def _get_code_artifacts(goal_id: str) -> dict:
    """Return artifacts from the most recent completed code task in this goal."""
    tasks = get(f"/api/goals/{goal_id}/tasks")
    if not isinstance(tasks, list):
        return {}
    for t in reversed(tasks):
        if t.get("task_type") == "code" and t.get("status") == "completed":
            return t.get("artifacts") or {}
    return {}


# ── Core: execute one task ────────────────────────────────────────────────────

async def execute_task(cli: str, task: dict) -> None:
    task_id  = task["task_id"]
    goal_id  = task["goal_id"]
    task_type = task.get("task_type", "general")
    description = task.get("description", "")

    # Set CLI busy
    patch(f"/api/agents/{cli}/status", {"status": "busy", "task": description[:80]})

    # Build prompt with intercept + prior context + task-specific instructions
    prior = get_prior_context(goal_id)
    suggestions, trace_id, suggestion_ids = intercept_task(description, task_type)
    goal_record = get(f"/api/goals/{goal_id}") or {}
    goal_text = goal_record.get("goal", description)
    task_instructions = _TASK_INSTRUCTIONS.get(task_type, "Complete the task thoroughly.")

    prompt = TASK_PROMPT_TEMPLATE.format(
        cli_name=cli.upper(),
        goal=goal_text,
        task_type=task_type,
        description=description,
        task_instructions=task_instructions,
        intercept_suggestions=suggestions,
        prior_context=prior,
    )

    logger.info("[%s] ▶ %s — %s", cli, task_type, description[:80])

    # Build bridge payload — include cwd if goal has a worktree registered
    worktree_path = goal_record.get("worktree_path")
    bridge_payload: dict = {"prompt": prompt, "timeout": CLI_TIMEOUT}
    if worktree_path:
        bridge_payload["cwd"] = worktree_path
        logger.info("[%s] Running in worktree: %s", cli, worktree_path)

    # Call CLI via bridge
    bridge_result = post(f"/cli/{cli}", bridge_payload, base=BRIDGE_URL, timeout=CLI_TIMEOUT + 10)

    if not bridge_result or not bridge_result.get("success"):
        err = (bridge_result or {}).get("output", "bridge call failed")[:200]
        logger.warning("[%s] Task %s failed: %s", cli, task_id, err)
        fail_task(goal_id, task_id, err)
        _affinity.record(cli, task_type, success=False)
        # Bridge/subprocess failure — suggestions may not have been usable; skip posttool
        patch(f"/api/agents/{cli}/status", {"status": "online"})
        return

    # Parse output
    out = parse_output(bridge_result.get("output", ""))

    # Auto-trigger deliberations
    for topic in out.deliberate_topics:
        trigger_deliberation(cli, topic, goal_text)

    # Auto-save experiences
    for insight in out.experiences:
        save_experience(cli, insight, task_type)

    # Complete task
    outcome = out.summary or out.key_output or out.raw[:300]
    combined_text = out.raw + " " + out.key_output
    artifacts = {
        "key_output":        out.key_output[:500],
        "confidence":        out.confidence,
        "raw_length":        len(out.raw),
        "tokens_estimated":  _estimate_tokens(out.raw),
        "lines_generated":   _count_lines(out.raw),
        "files_mentioned":   _extract_files(combined_text),
        "deliberated":       len(out.deliberate_topics),
        "experiences_saved": len(out.experiences),
        "cli":               cli,
        "task_type":         task_type,
        # Stored so evaluate task can deferred-vote these on PASS/NEEDS_REVISION
        "suggestion_ids":    suggestion_ids,
        "trace_id":          trace_id,
    }
    ok = complete_task(goal_id, task_id, outcome, artifacts)
    _affinity.record(cli, task_type, success=ok)
    logger.debug("[%s] Affinity: %s", cli, _affinity.stats_summary(cli))

    if ok and task_type == "evaluate":
        upper = outcome.upper()
        # Item 6: deferred voting — retrieve suggestion_ids stored by the code task
        code_arts = _get_code_artifacts(goal_id)
        code_suggestion_ids: list[str] = code_arts.get("suggestion_ids") or []

        if any(kw in upper for kw in ("NEEDS_REVISION", "NEEDS REVISION", "FAIL", "REWORK")):
            logger.info("[%s] Evaluate: NEEDS_REVISION — engine spawns new code+test+evaluate", cli)
            # Item 6: downvote — code-phase suggestions didn't prevent the quality issue
            for eid in code_suggestion_ids:
                vote_experience(eid, "down")
            if code_suggestion_ids:
                logger.info("[%s] Downvoted %d code-phase experiences (NEEDS_REVISION)", cli, len(code_suggestion_ids))
            report_posttool(
                trace_id, suggestion_ids,
                action_taken="followed: agent applied suggestions but evaluator requested revision — quality insufficient",
                transcript=outcome,
            )
        elif any(kw in upper for kw in ("PASS", "APPROVED", "LGTM")):
            logger.info("[%s] Evaluate: PASS — goal pipeline complete", cli)
            # Item 6: upvote — code-phase suggestions contributed to passing work
            for eid in code_suggestion_ids:
                vote_experience(eid, "up")
            if code_suggestion_ids:
                logger.info("[%s] Upvoted %d code-phase experiences (PASS)", cli, len(code_suggestion_ids))
            # Item 7: auto-save verified code output as a reusable "verified-solution" experience
            code_key_output = code_arts.get("key_output", "")
            if code_key_output:
                save_experience(
                    code_arts.get("cli", cli),
                    f"Verified solution: {code_key_output[:300]}",
                    "code",
                    extra_tags=["verified-solution", "auto"],
                )
            report_posttool(
                trace_id, suggestion_ids,
                action_taken="followed: agent applied suggestions and evaluator approved the result",
                transcript=outcome,
            )
        else:
            logger.info("[%s] Evaluate done (conf=%.2f) — engine decides iteration", cli, out.confidence)
            report_posttool(
                trace_id, suggestion_ids,
                action_taken=f"followed: evaluate completed with confidence {out.confidence:.2f}, verdict unclear",
                transcript=outcome,
            )
    else:
        label = "done" if ok else "complete-report failed"
        logger.info("[%s] %s task %s (conf=%.2f): %s", cli, label, task_id[:8], out.confidence, outcome[:80])
        if ok:
            # Non-evaluate task completed — report suggestions were used
            report_posttool(
                trace_id, suggestion_ids,
                action_taken=f"followed: {task_type} task completed successfully with confidence {out.confidence:.2f}",
                transcript=outcome,
            )

    patch(f"/api/agents/{cli}/status", {"status": "online"})


# ── Per-CLI loop ──────────────────────────────────────────────────────────────

async def cli_loop(cli: str) -> None:
    logger.info("[%s] Loop started (poll every %ds)", cli, POLL_INTERVAL)
    heartbeat_at = 0.0
    busy = False  # concurrency guard — one task at a time per CLI
    idle_streak = 0  # consecutive polls with no claimed task

    while True:
        now = time.monotonic()

        # Heartbeat
        if now - heartbeat_at > HEARTBEAT_INTERVAL:
            heartbeat(cli)
            if not busy:
                patch(f"/api/agents/{cli}/status", {"status": "online"})
            heartbeat_at = now

        if busy:
            await asyncio.sleep(POLL_INTERVAL)
            continue

        # Poll tasks — try each in affinity order until one claim succeeds
        tasks = get_available_tasks(cli)
        claimed_any = False
        for task in tasks:
            task_id = task.get("task_id")
            goal_id = task.get("goal_id")
            if task_id and goal_id:
                claimed = claim_task(goal_id, task_id, cli)
                if claimed:
                    busy = True
                    claimed_any = True
                    try:
                        await execute_task(cli, task)
                    finally:
                        busy = False
                    break  # one task at a time
        if not tasks:
            logger.debug("[%s] No tasks available", cli)
        elif not claimed_any:
            logger.debug("[%s] All %d visible tasks blocked (prerequisites or failed_by)", cli, len(tasks))

        if claimed_any:
            idle_streak = 0
        else:
            idle_streak += 1

        # Adaptive backoff: ramp up sleep when idle, reset on work found.
        # 0-2 idle polls → 15s, 3-5 → 30s, 6+ → 60s
        if idle_streak >= 6:
            sleep_time = 60
        elif idle_streak >= 3:
            sleep_time = 30
        else:
            sleep_time = POLL_INTERVAL
        if idle_streak in (3, 6):
            logger.info("[%s] Idle for %d consecutive polls — backing off to %ds", cli, idle_streak, sleep_time)
        await asyncio.sleep(sleep_time)


# ── Main ──────────────────────────────────────────────────────────────────────

def _load_bridge_config() -> None:
    """Fetch live config from bridge and update global runtime settings."""
    global ENGINE_URL, POLL_INTERVAL, CLI_TIMEOUT, MAX_ITERATIONS
    try:
        cfg = _req("GET", f"{BRIDGE_URL}/config", timeout=5)
        if not cfg:
            return
        if cfg.get("engine_url"):
            ENGINE_URL = cfg["engine_url"]
        if cfg.get("poll_interval"):
            POLL_INTERVAL = int(cfg["poll_interval"])
        if cfg.get("cli_timeout"):
            CLI_TIMEOUT = int(cfg["cli_timeout"])
        if cfg.get("max_iterations"):
            MAX_ITERATIONS = int(cfg["max_iterations"])
        logger.info(
            "Bridge config loaded — engine=%s poll=%ds timeout=%ds max_iter=%d",
            ENGINE_URL, POLL_INTERVAL, CLI_TIMEOUT, MAX_ITERATIONS,
        )
    except Exception as e:
        logger.warning("Could not load bridge config: %s (using env defaults)", e)


async def _wait_for_bridge() -> list[str]:
    """Block until CLI Bridge responds with at least one available CLI.

    Uses exponential backoff (5s → 10s → … capped at 60s) so the container
    survives being started before the host CLI Bridge is running.
    The loop never exits — Docker restart policy is irrelevant here.
    """
    attempt = 0
    while True:
        available = get_available_clis()
        if available:
            logger.info("CLI Bridge ready — available CLIs: %s", available)
            return available
        attempt += 1
        wait = min(60, 5 * attempt)
        logger.info(
            "CLI Bridge not reachable at %s — retry in %ds (attempt %d) …",
            BRIDGE_URL, wait, attempt,
        )
        await asyncio.sleep(wait)


async def _watch_bridge(available: list[str]) -> None:
    """Periodically re-check which CLIs are available on the bridge.

    If the bridge goes down and comes back, or new CLIs are enabled,
    we detect that here and restart the per-CLI loops automatically.
    Runs as a background task alongside cli_loop coroutines.
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL * 2)
        current = get_available_clis()
        added   = [c for c in current  if c not in available]
        removed = [c for c in available if c not in current]
        if added or removed:
            logger.info(
                "Bridge CLI set changed — added: %s  removed: %s — restarting loops",
                added, removed,
            )
            # Trigger a clean restart of all loops by cancelling the gather task.
            # asyncio.gather propagates CancelledError to the caller.
            for task in asyncio.all_tasks():
                if task.get_name().startswith("cli-loop-"):
                    task.cancel()


async def main(engine: str, bridge: str) -> None:
    global ENGINE_URL, BRIDGE_URL
    ENGINE_URL = engine
    BRIDGE_URL = bridge

    logger.info("=== Loomind Agent Loop Runner ===")
    logger.info("Engine: %s | Bridge: %s", ENGINE_URL, BRIDGE_URL)

    # Wait for bridge — blocks here if bridge isn't up yet (no exit / no crash loop)
    available = await _wait_for_bridge()

    _load_bridge_config()
    logger.info("Runtime — engine=%s poll=%ds cli_timeout=%ds max_iter=%d",
                ENGINE_URL, POLL_INTERVAL, CLI_TIMEOUT, MAX_ITERATIONS)

    # Deregister any CLIs that are NOT available — cleans up stale registrations from prior runs
    for cli in CLI_ROLES:
        if cli not in available:
            _req("DELETE", f"{ENGINE_URL}/api/agents/cli-{cli}", timeout=5)
            logger.info("Deregistered unavailable CLI from engine: cli-%s", cli)

    # Register all available CLIs as agents in engine
    for cli in available:
        register_cli_as_agent(cli)

    # Run concurrent loops — one per CLI + bridge watcher
    loops = [
        asyncio.create_task(cli_loop(cli), name=f"cli-loop-{cli}")
        for cli in available
    ]
    await asyncio.gather(*loops)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Loomind Agent Loop Runner")
    parser.add_argument("--engine", default=ENGINE_URL, help="Engine base URL")
    parser.add_argument("--bridge", default=BRIDGE_URL, help="CLI Bridge base URL")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.engine, args.bridge))
    except KeyboardInterrupt:
        logger.info("Agent Loop stopped.")
