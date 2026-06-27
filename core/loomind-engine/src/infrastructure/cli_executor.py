"""
CLI Executor — Headless subprocess runner for multi-CLI fleet.

Spawns CLI tools in non-interactive mode, streams their stdout to the
EventBus (visible in Terminal page), and returns parsed CLIResult.

Supported CLIs and their headless invocation:
  claude  → claude --print "<prompt>"
  grok    → grok "<prompt>"
  codex   → codex "<prompt>"
  agy     → agy "<prompt>"

Output parsing: tries JSON on the last line first, then falls back
to keyword heuristics (AGREE / DISAGREE / NEED_HUMAN, HIGH / LOW).

Phase 12 — Multi-CLI Deliberation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus

logger = logging.getLogger(__name__)

# When set, CLIExecutor calls this HTTP bridge instead of spawning subprocesses.
# Set CLI_BRIDGE_URL=http://host.docker.internal:8083 in docker-compose.yml.
_CLI_BRIDGE_URL = os.getenv("CLI_BRIDGE_URL", "").rstrip("/")

# Headless invocation templates — {prompt} is substituted at call time
# claude: --print      → single-turn, stdout, exit
# grok:   -p           → single-turn, stdout, exit (confirmed v0.2.51)
# agy:    --print / -p → single-turn, non-interactive, stdout (confirmed)
# codex:  exec         → non-interactive subcommand (confirmed)
_CLI_TEMPLATES: dict[str, list[str]] = {
    "claude": ["claude", "--print", "{prompt}"],
    "grok":   ["grok",   "-p",      "{prompt}"],
    "agy":    ["agy",    "--print", "{prompt}"],
    "codex":  ["codex",  "exec",    "{prompt}"],
}

_DEFAULT_TIMEOUT = 300  # seconds


@dataclass
class CLIResult:
    cli: str
    success: bool
    output: str
    exit_code: int
    duration_ms: float
    vote: str = "abstain"
    confidence: float = 0.5
    recommendation: str = ""


class CLIExecutor:
    """Headless CLI subprocess runner. One shared instance per engine process."""

    def __init__(self, event_bus: "EventBus", default_timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._bus = event_bus
        self._timeout = default_timeout

    # ── Public API ────────────────────────────────────────────────────────────

    def is_available(self, cli: str) -> bool:
        """True if the CLI is reachable — via bridge (HTTP) or local PATH."""
        if _CLI_BRIDGE_URL:
            return True  # bridge answers for availability; let run() surface 503
        binary = _CLI_TEMPLATES.get(cli, [cli])[0]
        return shutil.which(binary) is not None

    async def run(
        self,
        cli: str,
        prompt: str,
        deliberation_id: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> CLIResult:
        """Spawn CLI headless, stream output to EventBus, return parsed result."""
        template = _CLI_TEMPLATES.get(cli)
        if not template:
            return self._error(cli, f"Unknown CLI: {cli}")

        # Bridge mode: engine is in Docker, CLIs run on host
        if _CLI_BRIDGE_URL:
            return await self._run_via_bridge(cli, prompt, deliberation_id, timeout)

        if not self.is_available(cli):
            return self._error(cli, f"{cli} not found on PATH — install or add to PATH")

        cmd = [part.replace("{prompt}", prompt) for part in template]
        t0 = datetime.now(timezone.utc).timestamp()

        self._emit(cli, "INFO", f"▶ [{cli.upper()}] {prompt[:100].strip()}", deliberation_id)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None

            output_lines: list[str] = []

            async def _drain() -> None:
                async for raw in proc.stdout:  # type: ignore[union-attr]
                    line = raw.decode(errors="replace").rstrip()
                    output_lines.append(line)
                    self._emit(cli, "INFO", line, deliberation_id)

            try:
                await asyncio.wait_for(_drain(), timeout=timeout or self._timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                output = "\n".join(output_lines)
                self._emit(cli, "WARNING", f"⏱ [{cli.upper()}] TIMEOUT after {timeout or self._timeout}s", deliberation_id)
                return CLIResult(
                    cli=cli, success=False,
                    output=output + "\n[TIMEOUT]",
                    exit_code=-1,
                    duration_ms=self._ms(t0),
                )

            await proc.wait()
            output = "\n".join(output_lines)
            success = (proc.returncode == 0)
            result = CLIResult(
                cli=cli,
                success=success,
                output=output,
                exit_code=proc.returncode or 0,
                duration_ms=self._ms(t0),
            )
            self._parse(result)
            level = "INFO" if success else "WARNING"
            self._emit(cli, level, f"■ [{cli.upper()}] exit={proc.returncode} ({result.duration_ms:.0f}ms) vote={result.vote}", deliberation_id)
            return result

        except Exception as exc:
            logger.exception("CLIExecutor error for %s", cli)
            return CLIResult(cli=cli, success=False, output=str(exc), exit_code=-1, duration_ms=self._ms(t0))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _emit(self, cli: str, level: str, message: str, deliberation_id: Optional[str] = None) -> None:
        payload: dict = {"level": level, "logger": f"cli.{cli}", "message": message}
        if deliberation_id:
            payload["deliberation_id"] = deliberation_id
        self._bus.broadcast({"event": "log", "payload": payload})

    @staticmethod
    def _ms(t0: float) -> float:
        return (datetime.now(timezone.utc).timestamp() - t0) * 1000

    @staticmethod
    def _error(cli: str, msg: str) -> CLIResult:
        return CLIResult(cli=cli, success=False, output=msg, exit_code=-1, duration_ms=0.0)

    async def _run_via_bridge(
        self,
        cli: str,
        prompt: str,
        deliberation_id: Optional[str],
        timeout: Optional[int],
    ) -> CLIResult:
        """Call CLI Bridge HTTP server — used when engine runs inside Docker."""
        t0 = datetime.now(timezone.utc).timestamp()
        self._emit(cli, "INFO", f"▶ [{cli.upper()}] (bridge) {prompt[:100].strip()}", deliberation_id)
        url = f"{_CLI_BRIDGE_URL}/cli/{cli}"
        req_timeout = (timeout or self._timeout) + 5  # extra buffer for HTTP overhead
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json={"prompt": prompt, "timeout": timeout or self._timeout},
                    timeout=req_timeout,
                )
                if resp.status_code == 503:
                    msg = resp.json().get("detail", f"{cli} not available on bridge host")
                    self._emit(cli, "WARNING", f"⚠ [{cli.upper()}] {msg}", deliberation_id)
                    return self._error(cli, msg)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            return self._error(cli, f"[BRIDGE TIMEOUT] {cli} did not respond in {req_timeout}s")
        except httpx.HTTPError as exc:
            return self._error(cli, f"[BRIDGE ERROR] {exc}")

        result = CLIResult(
            cli=cli,
            success=data.get("success", False),
            output=data.get("output", ""),
            exit_code=data.get("exit_code", -1),
            duration_ms=data.get("duration_ms", self._ms(t0)),
        )
        # Stream full output as one block to EventBus
        for line in result.output.split("\n"):
            if line.strip():
                self._emit(cli, "INFO", line, deliberation_id)
        self._parse(result)
        level = "INFO" if result.success else "WARNING"
        self._emit(cli, level, f"■ [{cli.upper()}] exit={result.exit_code} ({result.duration_ms:.0f}ms) vote={result.vote}", deliberation_id)
        return result

    def _parse(self, result: CLIResult) -> None:
        """Extract vote/confidence/recommendation.

        Priority:
        1. Last JSON line (structured output from deliberation prompt)
        2. Keyword heuristics in the full output
        """
        lines = result.output.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    result.vote = str(data.get("vote", "abstain")).lower()
                    result.confidence = float(data.get("confidence", 0.5))
                    result.recommendation = str(data.get("recommendation", "")) or result.output
                    return
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

        # Keyword heuristics
        upper = result.output.upper()
        if "NEED_HUMAN" in upper or "NEED HUMAN" in upper:
            result.vote = "need_human"
            result.confidence = 1.0
        elif "COUNTER_PROPOSE" in upper or "COUNTER-PROPOSE" in upper:
            result.vote = "counter_propose"
        elif "DISAGREE" in upper:
            result.vote = "disagree"
        elif "AGREE" in upper:
            result.vote = "agree"
            result.confidence = max(result.confidence, 0.75)

        if "HIGH CONFIDENCE" in upper or "CONFIDENCE: HIGH" in upper:
            result.confidence = max(result.confidence, 0.85)
        elif "LOW CONFIDENCE" in upper or "CONFIDENCE: LOW" in upper:
            result.confidence = min(result.confidence, 0.35)

        result.recommendation = result.output
