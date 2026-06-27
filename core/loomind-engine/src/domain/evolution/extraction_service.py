"""
Extraction Service — Turns session transcripts into T3 lessons.

Uses LLM to identify retry loops, corrections, test failures, mistakes
in session transcripts and stores extracted lessons in T3 (raw/staging).

Requirements: 8.1–8.7
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from src.domain.evolution.tiers import TIER_COLLECTION, KnowledgeTier
from src.domain.models import Experience, ExtractResult
from src.infrastructure.embedder import Embedder
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.qdrant_client import QdrantStore

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_LENGTH = 100_000
MAX_LESSONS_PER_REQUEST = 10
DEDUP_COSINE_THRESHOLD = 0.95

EXTRACT_PROMPT = """Analyze this coding session transcript. Find:
- Retry loops (same command run multiple times)
- Corrections (fixing earlier mistakes)
- Test failures and fixes
- Mistakes and their resolutions

For each lesson, output a Q&A pair.
Max {max_lessons} lessons. JSON only:
{{"lessons": [{{"question": "What situation occurred?", "answer": "What should be done instead?"}}]}}

TRANSCRIPT:
{transcript}"""


class ExtractionService:
    """Extracts lessons from session transcripts into T3."""

    def __init__(self, store: QdrantStore, embedder: Embedder, llm: LLMClient) -> None:
        self.store = store
        self.embedder = embedder
        self.llm = llm

    async def extract(self, transcript: str, session_id: str, *, max_lessons: int = MAX_LESSONS_PER_REQUEST) -> ExtractResult:
        """Extract lessons from transcript, dedup against T3, store new ones."""
        transcript = (transcript or "").strip()

        # Validation
        if not transcript:
            return ExtractResult(created=0, deduped=0, lesson_ids=[])
        if len(transcript) > MAX_TRANSCRIPT_LENGTH:
            return ExtractResult(created=0, deduped=0, lesson_ids=[])

        # LLM extraction
        prompt = EXTRACT_PROMPT.format(transcript=transcript[:50000], max_lessons=max_lessons)
        try:
            raw = await self.llm.complete(prompt, json_mode=True)
            lessons = self._parse_lessons(raw, max_lessons)
        except Exception:
            logger.exception("Extraction LLM failed; returning zero lessons")
            return ExtractResult(created=0, deduped=0, lesson_ids=[])

        if not lessons:
            return ExtractResult(created=0, deduped=0, lesson_ids=[])

        # Dedup and store
        created = 0
        deduped = 0
        lesson_ids: list[str] = []
        t3_col = TIER_COLLECTION[KnowledgeTier.T3_RAW]

        for lesson in lessons:
            q = lesson.get("question", "")
            a = lesson.get("answer", "")
            if not q or not a:
                continue

            text = f"{q} {a}"
            try:
                vec = self.embedder.embed(text)
            except Exception:
                continue

            # Check dedup against T3
            if self._is_duplicate(vec):
                deduped += 1
                continue

            exp = Experience(
                id=str(uuid.uuid4()),
                title=q[:200],
                description=a,
                category="lesson",
                tags=["auto-extracted", f"session:{session_id}"],
                tier=KnowledgeTier.T3_RAW,
                confidence=0.3,
            )
            try:
                self.store.upsert_experience(t3_col, exp, vec)
                created += 1
                lesson_ids.append(exp.id)
            except Exception:
                logger.exception("Failed to store extracted lesson")

        return ExtractResult(created=created, deduped=deduped, lesson_ids=lesson_ids)

    def _is_duplicate(self, vec: list[float]) -> bool:
        """Check if a vector is too similar to existing T3 entries."""
        try:
            results = self.store.search_tiers(
                tiers=(KnowledgeTier.T3_RAW,),
                vector=vec,
                top_k_per_tier=1,
            )
            # T3 threshold in search_tiers is 0.55 by design,
            # but we override by checking score >= 0.95
            for r in results:
                if r.get("score", 0.0) >= DEDUP_COSINE_THRESHOLD:
                    return True
        except Exception:
            pass
        return False

    def _parse_lessons(self, raw: str, max_n: int) -> list[dict[str, str]]:
        try:
            data = json.loads(raw)
            lessons = data.get("lessons", [])
            return lessons[:max_n] if isinstance(lessons, list) else []
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse extraction response")
            return []
