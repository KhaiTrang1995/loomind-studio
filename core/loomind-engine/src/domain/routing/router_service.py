"""
Router Service — 3-layer fastest-first model routing.

Algorithm 6: keyword → history → brain LLM.
Requirements: 5.1–5.7
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.domain.models import RoutingDecision, TaskRoute, TaskTier
from src.infrastructure.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ── Keyword patterns ──────────────────────────────────────────────────────

KEYWORD_RULES: list[dict[str, Any]] = [
    {"keywords": ["debug", "race", "deadlock", "memory leak", "segfault", "crash"], "tier": "hot", "effort": "high", "confidence": 0.85},
    {"keywords": ["architect", "design", "refactor major", "migrate"], "tier": "hot", "effort": "high", "confidence": 0.80},
    {"keywords": ["security", "vulnerability", "exploit", "injection"], "tier": "hot", "effort": "high", "confidence": 0.82},
    {"keywords": ["implement", "create", "build", "add feature"], "tier": "warm", "effort": "medium", "confidence": 0.80},
    {"keywords": ["fix", "patch", "update", "modify"], "tier": "warm", "effort": "medium", "confidence": 0.80},
    {"keywords": ["test", "unit test", "integration test"], "tier": "warm", "effort": "medium", "confidence": 0.80},
    {"keywords": ["document", "readme", "comment", "changelog"], "tier": "cold", "effort": "low", "confidence": 0.85},
    {"keywords": ["format", "lint", "style", "typo"], "tier": "cold", "effort": "low", "confidence": 0.88},
    {"keywords": ["research", "compare", "evaluate", "pros cons"], "tier": "cold", "effort": "low", "confidence": 0.80},
]

# ── Model resolution ──────────────────────────────────────────────────────

TIER_MODELS: dict[str, str] = {
    "hot": "claude-sonnet-4-6",
    "warm": "deepseek-v4-flash",
    "cold": "gemini-2.5-flash",
}

TIER_FALLBACKS: dict[str, list[str]] = {
    "hot": ["gpt-4o", "deepseek-v4-flash"],
    "warm": ["gemini-2.5-flash", "claude-sonnet-4-6"],
    "cold": ["deepseek-v4-flash", "gpt-4o-mini"],
}

TIER_EFFORT: dict[str, str] = {
    "hot": "high",
    "warm": "medium",
    "cold": "low",
}


class RouterService:
    """3-layer fastest-first model routing."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._history: list[dict[str, Any]] = []  # in-memory history

    async def route_model(self, task: str, runtime: str | None = None) -> RoutingDecision:
        """Route a task to the optimal model tier."""
        task = (task or "").strip()
        if not task:
            raise ValueError("Non-empty task description required")

        # Layer 1: keyword (~0ms)
        hit = self._keyword_match(task)
        if hit and hit["confidence"] >= 0.8:
            tier = hit["tier"]
            return RoutingDecision(
                tier=TaskTier(tier),
                model=TIER_MODELS[tier],
                reasoning_effort=hit.get("effort", TIER_EFFORT[tier]),
                confidence=hit["confidence"],
                source="keyword",
                fallback_chain=TIER_FALLBACKS[tier],
            )

        # Layer 2: history (~50ms)
        hist_result = self._history_match(task)
        if hist_result:
            tier = hist_result["tier"]
            return RoutingDecision(
                tier=TaskTier(tier),
                model=TIER_MODELS[tier],
                reasoning_effort=TIER_EFFORT[tier],
                confidence=hist_result["confidence"],
                source="history",
                fallback_chain=TIER_FALLBACKS[tier],
            )

        # Layer 3: brain LLM (~200ms, fail-open)
        try:
            import asyncio
            brain = await asyncio.wait_for(self._brain_classify(task), timeout=2.0)
            tier = brain.get("tier", "warm")
            if tier not in TIER_MODELS:
                tier = "warm"
            self._history.append({"task": task, "tier": tier})
            return RoutingDecision(
                tier=TaskTier(tier),
                model=TIER_MODELS[tier],
                reasoning_effort=brain.get("effort", TIER_EFFORT[tier]),
                confidence=brain.get("confidence", 0.6),
                source="brain",
                fallback_chain=TIER_FALLBACKS[tier],
            )
        except Exception:
            logger.warning("Brain LLM failed; returning WARM default (fail-open)")
            return RoutingDecision(
                tier=TaskTier.WARM,
                model=TIER_MODELS["warm"],
                reasoning_effort="medium",
                confidence=0.4,
                source="brain",
                fallback_chain=TIER_FALLBACKS["warm"],
            )

    async def route_task(self, task: str) -> TaskRoute:
        """Higher-level workflow routing."""
        task = (task or "").strip()
        if not task:
            raise ValueError("Non-empty task description required")

        lower = task.lower()

        # High-stakes → council
        council_indicators = ["should we", "compare", "trade-off", "best approach", "pros and cons", "which is better"]
        if any(ind in lower for ind in council_indicators):
            return TaskRoute(
                workflow="council",
                rounds=2,
                models=[TIER_MODELS["hot"], TIER_MODELS["warm"], TIER_MODELS["cold"]],
                auto_triggered=True,
                confidence=0.85,
            )

        # Research indicators
        research_indicators = ["research", "investigate", "analyze", "review", "audit"]
        if any(ind in lower for ind in research_indicators):
            return TaskRoute(
                workflow="research_first",
                rounds=1,
                models=[TIER_MODELS["cold"], TIER_MODELS["warm"]],
                auto_triggered=False,
                confidence=0.7,
            )

        # Default: single
        decision = await self.route_model(task)
        return TaskRoute(
            workflow="single",
            rounds=1,
            models=[decision.model],
            auto_triggered=False,
            confidence=decision.confidence,
        )

    def _keyword_match(self, task: str) -> dict[str, Any] | None:
        lower = task.lower()
        best = None
        best_count = 0
        for rule in KEYWORD_RULES:
            count = sum(1 for kw in rule["keywords"] if kw in lower)
            if count > best_count:
                best_count = count
                best = rule
        if best and best_count > 0:
            return best
        return None

    def _history_match(self, task: str) -> dict[str, Any] | None:
        if len(self._history) < 3:
            return None
        lower = task.lower()
        words = set(lower.split())
        matches = []
        for h in self._history[-50:]:
            h_words = set(h["task"].lower().split())
            overlap = len(words & h_words) / max(len(words | h_words), 1)
            if overlap >= 0.75:
                matches.append(h)
        if len(matches) < 3:
            return None
        tiers = [m["tier"] for m in matches]
        most_common = max(set(tiers), key=tiers.count)
        agreement = tiers.count(most_common) / len(tiers)
        if agreement >= 0.6:
            return {"tier": most_common, "confidence": agreement}
        return None

    async def _brain_classify(self, task: str) -> dict[str, Any]:
        prompt = f'Classify this task into a model tier. JSON only:\n{{"tier": "hot"|"warm"|"cold", "effort": "low"|"medium"|"high", "confidence": 0.0-1.0}}\n\nTask: {task}'
        raw = await self.llm.complete(prompt, json_mode=True)
        return json.loads(raw)
