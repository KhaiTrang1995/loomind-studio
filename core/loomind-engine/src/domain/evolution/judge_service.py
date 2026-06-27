"""
Judge Service — Async LLM evaluator for closed-loop learning.

Evaluates whether an agent FOLLOWED, IGNORED, or found a suggestion
IRRELEVANT/UNCLEAR. Used by the background worker to process posttool
feedback asynchronously.

Algorithm 2 from the design document.
Requirements: 3.2, 3.3, 3.4, 3.5
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.domain.evolution.tiers import TIER_COLLECTION, KnowledgeTier
from src.domain.models import JudgeItem, Observation
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.qdrant_client import QdrantStore

logger = logging.getLogger(__name__)

# Judge prompt template
JUDGE_PROMPT_TEMPLATE = """You are a judge. For each suggestion-action pair, determine the verdict.

Respond with JSON only: {{"verdicts": [{{"verdict": "FOLLOWED"|"IGNORED"|"IRRELEVANT"|"UNCLEAR", "rationale": "short reason"}}]}}

PAIRS:
{pairs_text}
"""

# Verdict → counter field mapping
VERDICT_COUNTER_MAP = {
    "FOLLOWED": "followed_count",
    "IGNORED": "ignored_count",
    "IRRELEVANT": "ignored_count",
    "UNCLEAR": None,  # no counter change
}


class JudgeService:
    """Async LLM evaluator. Decides whether agent FOLLOWED/IGNORED a suggestion."""

    def __init__(self, llm: LLMClient, store: QdrantStore) -> None:
        self.llm = llm
        self.store = store

    async def judge_batch(self, items: list[JudgeItem]) -> list[Observation]:
        """Evaluate a batch (≤16) of (suggestion, action_taken) pairs.

        Returns one Observation per item with verdict + rationale.
        Fail-open: on LLM error returns verdict=UNCLEAR (no signal lost).
        """
        if not items:
            return []

        # Build prompt
        pairs_text = self._build_pairs_text(items)
        prompt = JUDGE_PROMPT_TEMPLATE.format(pairs_text=pairs_text)

        # Call LLM with fail-open
        try:
            raw = await self.llm.complete(prompt, json_mode=True)
            verdicts = self._parse_verdicts(raw, len(items))
        except Exception:
            logger.exception("Judge LLM call failed; assigning UNCLEAR to all items (fail-open)")
            verdicts = [{"verdict": "UNCLEAR", "rationale": "LLM unavailable"} for _ in items]

        # Build observations and bump counters
        observations: list[Observation] = []
        for item, verdict_data in zip(items, verdicts):
            verdict_label = verdict_data.get("verdict", "UNCLEAR")
            if verdict_label not in ("FOLLOWED", "IGNORED", "IRRELEVANT", "UNCLEAR"):
                verdict_label = "UNCLEAR"

            obs = Observation(
                experience_id=item.suggestion_id,
                session_id=item.trace_id,
                verdict=verdict_label,
                rationale=verdict_data.get("rationale", ""),
                judge_model=self.llm.model,
            )
            observations.append(obs)

            # Bump counters atomically
            await self._bump_counter(item.suggestion_id, verdict_label)

        return observations

    async def _bump_counter(self, experience_id: str, verdict: str) -> None:
        """Atomically increment followed_count or ignored_count on the experience."""
        counter_field = VERDICT_COUNTER_MAP.get(verdict)
        if counter_field is None:
            return  # UNCLEAR → no counter change

        # Search across tiers to find the experience
        for tier in (
            KnowledgeTier.T0_PRINCIPLE,
            KnowledgeTier.T1_BEHAVIORAL,
            KnowledgeTier.T2_QA_CACHE,
            KnowledgeTier.T3_RAW,
        ):
            collection = TIER_COLLECTION[tier]
            try:
                payload = self.store.get_experience(collection, experience_id)
            except Exception:
                continue

            if payload is None:
                continue

            # Found it — increment the counter
            current_value = int(payload.get(counter_field, 0))
            try:
                self.store.client.set_payload(
                    collection_name=collection,
                    payload={counter_field: current_value + 1},
                    points=[experience_id],
                )
                logger.debug(
                    "Bumped %s on %s in '%s': %d → %d",
                    counter_field,
                    experience_id,
                    collection,
                    current_value,
                    current_value + 1,
                )
            except Exception:
                logger.exception(
                    "Failed to bump %s on %s in '%s'",
                    counter_field,
                    experience_id,
                    collection,
                )
            return

        logger.warning("Could not find experience %s in any tier to bump counter", experience_id)

    def _build_pairs_text(self, items: list[JudgeItem]) -> str:
        """Build the pairs text for the judge prompt."""
        lines = []
        for i, item in enumerate(items, 1):
            snippet = (item.transcript_snippet or "")[:300]
            lines.append(
                f"{i}. Suggestion ID: {item.suggestion_id}\n"
                f"   Action taken: {item.action_taken}\n"
                f"   Context: {snippet}"
            )
        return "\n".join(lines)

    def _parse_verdicts(self, raw: str, expected_n: int) -> list[dict[str, Any]]:
        """Parse the LLM JSON response into verdict dicts."""
        try:
            data = json.loads(raw)
            verdicts = data.get("verdicts", [])
            if isinstance(verdicts, list) and len(verdicts) >= expected_n:
                return verdicts[:expected_n]
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("Failed to parse judge LLM response: %s", raw[:200])

        # Pad with UNCLEAR if parsing fails or returns fewer verdicts
        result = []
        try:
            data = json.loads(raw)
            result = data.get("verdicts", [])[:expected_n]
        except Exception:
            pass

        while len(result) < expected_n:
            result.append({"verdict": "UNCLEAR", "rationale": "Parse failure"})
        return result
