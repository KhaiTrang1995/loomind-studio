"""
BA Agent Service — Analyzes goals and decomposes them into User Stories with AC and Fibonacci
story points. Uses LLM for intelligent decomposition. Classifies each task as AUTO/HITL/SECURITY.

Phase 11 — Agentic Brain.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

from src.domain.models import (
    AcceptanceCriteria,
    BAAnalysisResult,
    FIBONACCI_POINTS,
    TaskMode,
    UserStory,
)

logger = logging.getLogger(__name__)

# Keywords that force SECURITY mode
_SECURITY_KEYWORDS = (
    "auth", "token", "secret", "password", "credential", "key", "encrypt",
    "decrypt", "cert", "ssl", "tls", "oauth", "jwt", "permission", "role",
    "bảo mật", "mật khẩu", "xác thực", "phân quyền",
)

# Keywords that force HITL mode (non-security but sensitive)
_HITL_KEYWORDS = (
    "delete", "drop", "remove", "xóa", "xoá", "truncate", "destroy",
    "reset", "overwrite", "migrate", "production", "prod",
)

_DECOMPOSE_PROMPT = """You are a Senior Business Analyst. Analyze the following goal and decompose it into User Stories.

GOAL: {goal}
{prior_context_section}
Rules:
1. Create 3-7 User Stories that together fully deliver the goal
2. Each story must have: title, description (As a... I want... So that...), 2-3 Acceptance Criteria (Given/When/Then)
3. Estimate Fibonacci story points: 1, 2, 3, 5, 8, 13 (complexity + effort)
4. Classify task_mode: "auto" (safe, reversible), "hitl" (needs human review), "security" (auth/credentials/permissions)
5. Choose task_type: "research", "code", "test", or "evaluate"
6. Respond ONLY with valid JSON, no markdown, no explanation

JSON schema:
{{
  "user_stories": [
    {{
      "title": "string",
      "description": "string",
      "acceptance_criteria": [
        {{"given": "string", "when": "string", "then": "string"}}
      ],
      "story_points": 1,
      "task_mode": "auto|hitl|security",
      "task_type": "research|code|test|evaluate"
    }}
  ],
  "analysis_notes": "string"
}}"""


def _nearest_fibonacci(n: int) -> int:
    """Clamp an integer to nearest valid Fibonacci story point."""
    return min(FIBONACCI_POINTS, key=lambda f: abs(f - max(1, min(n, 13))))


def _classify_mode(title: str, description: str) -> str:
    """Override LLM classification with deterministic keyword rules."""
    text = (title + " " + description).lower()
    for kw in _SECURITY_KEYWORDS:
        if kw in text:
            return TaskMode.SECURITY
    for kw in _HITL_KEYWORDS:
        if kw in text:
            return TaskMode.HITL
    return TaskMode.AUTO


class BAService:
    """Uses LLM to decompose a goal into User Stories with AC and story points."""

    def __init__(self, llm) -> None:
        self._llm = llm

    async def analyze_goal(
        self,
        goal: str,
        goal_id: Optional[str] = None,
        prior_context: str = "",
    ) -> BAAnalysisResult:
        """Call LLM to decompose goal → User Stories. Falls back to heuristic if LLM fails."""
        gid = goal_id or str(uuid.uuid4())
        ctx_section = (
            f"\nSIMILAR PAST GOALS (use to calibrate story points and task types):\n{prior_context}\n"
            if prior_context else ""
        )
        prompt = _DECOMPOSE_PROMPT.format(goal=goal, prior_context_section=ctx_section)

        raw = ""
        try:
            raw = await self._llm.complete(prompt, max_tokens=2000)
            data = self._parse_json(raw)
            stories = self._build_stories(data.get("user_stories", []))
            notes = data.get("analysis_notes", "")
        except Exception as exc:
            logger.warning("BA LLM analysis failed (%s), using heuristic fallback", exc)
            stories = self._heuristic_decompose(goal)
            notes = "Heuristic fallback — LLM unavailable"

        # Deterministic security override
        for s in stories:
            forced = _classify_mode(s.title, s.description)
            if forced != TaskMode.AUTO:
                s.task_mode = forced

        total = sum(s.story_points for s in stories)
        logger.info("BA analyzed goal '%s': %d stories, %d total points", goal[:60], len(stories), total)

        return BAAnalysisResult(
            goal_id=gid,
            goal=goal,
            user_stories=stories,
            total_points=total,
            analysis_notes=notes,
        )

    # ── Private helpers ──────────────────────────────────────────────────

    def _parse_json(self, raw: str) -> dict:
        """Extract JSON from LLM output (handles markdown code fences)."""
        text = raw.strip()
        # Strip ```json ... ``` fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)

    def _build_stories(self, raw_stories: list[dict]) -> list[UserStory]:
        stories = []
        for s in raw_stories:
            pts = _nearest_fibonacci(int(s.get("story_points", 1)))
            mode_raw = str(s.get("task_mode", "auto")).lower()
            try:
                mode = TaskMode(mode_raw)
            except ValueError:
                mode = TaskMode.AUTO
            criteria = [
                AcceptanceCriteria(
                    given=ac.get("given", ""),
                    when=ac.get("when", ""),
                    then=ac.get("then", ""),
                )
                for ac in s.get("acceptance_criteria", [])
            ]
            stories.append(UserStory(
                title=s.get("title", "Untitled story"),
                description=s.get("description", ""),
                acceptance_criteria=criteria,
                story_points=pts,
                task_mode=mode,
                task_type=s.get("task_type", "code"),
            ))
        return sorted(stories, key=lambda x: x.story_points, reverse=True)

    def _heuristic_decompose(self, goal: str) -> list[UserStory]:
        """Minimal fallback when LLM is unavailable."""
        return [
            UserStory(
                title=f"Research: {goal[:60]}",
                description=f"As an agent, I want to research and understand the context for: {goal}",
                acceptance_criteria=[AcceptanceCriteria(
                    given="Agent has access to the codebase",
                    when="Research task is claimed",
                    then="A summary of findings is produced",
                )],
                story_points=3,
                task_mode=TaskMode.AUTO,
                task_type="research",
            ),
            UserStory(
                title=f"Implement: {goal[:60]}",
                description=f"As an agent, I want to implement the solution for: {goal}",
                acceptance_criteria=[AcceptanceCriteria(
                    given="Research is complete",
                    when="Code task is claimed",
                    then="Implementation is committed and tests pass",
                )],
                story_points=5,
                task_mode=TaskMode.AUTO,
                task_type="code",
            ),
            UserStory(
                title=f"Test & verify: {goal[:60]}",
                description=f"As an agent, I want to verify the implementation for: {goal}",
                acceptance_criteria=[AcceptanceCriteria(
                    given="Implementation is complete",
                    when="Test task is claimed",
                    then="All AC pass and coverage is acceptable",
                )],
                story_points=2,
                task_mode=TaskMode.AUTO,
                task_type="test",
            ),
        ]
