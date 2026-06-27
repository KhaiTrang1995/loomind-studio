"""
Experience Service — Core business logic with v1+v2 intercept pipeline.

Layer 1: Read-only Filter (client-side + server-side, 0ms)
Layer 2: Semantic Search via Qdrant (embed action → query top-K, <50ms)
Layer 3: LLM Anti-Noise Filter (ask LLM which results are relevant, <500ms)

v2 additions:
- Secret redaction before embedding/LLM calls
- PIL enrichment → parallel multi-tier search → 1-hop graph → rank → LLM filter
- trace_id for posttool linkage
- Session deduplication with TTL reset
- Budget cap at 8 suggestions
- Usage tracking (last_used_at, usage_count)
- v1 backward compatibility: create→T2, feedback→counter bump
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from src.domain.evolution.tiers import TIER_COLLECTION
from src.domain.models import (
    ActionType,
    CreateExperienceRequest,
    Experience,
    FeedbackRequest,
    InterceptRequest,
    InterceptResponse,
    InterceptResponseV2,
    KnowledgeTier,
    Observation,
    Suggestion,
    UpdateExperienceRequest,
)
from src.domain.pil.pil_enricher import PILEnricher
from src.domain.ranking.ranker import build_candidate_from_hit, rank
from src.infrastructure.embedder import Embedder
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.readonly_filter import is_readonly as hardened_is_readonly
from src.infrastructure.qdrant_client import QdrantStore
from src.infrastructure.redaction import redact_secrets

logger = logging.getLogger(__name__)

# Budget cap: max suggestions per intercept response
BUDGET_CAP = 8

# Always-load tiers for intercept
ALWAYS_LOAD_TIERS = (KnowledgeTier.T0_PRINCIPLE, KnowledgeTier.T1_BEHAVIORAL)

# Per-agent session TTL: seen-set expires after this many seconds of inactivity
_SESSION_TTL = 300.0  # 5 minutes

# Thread pool for Qdrant searches and embedding (CPU-bound in sentence-transformers)
_SEARCH_POOL = ThreadPoolExecutor(
    max_workers=min(32, (os.cpu_count() or 4) + 4),
    thread_name_prefix="qdrant-search",
)


class ExperienceService:
    """Orchestrates the 3-layer intercept pipeline + v2 enhancements."""

    def __init__(
        self,
        qdrant: QdrantStore,
        embedder: Embedder,
        llm: LLMClient,
        collection: str = "experiences",
        *,
        pil: PILEnricher | None = None,
        graph: Any = None,
    ) -> None:
        self.qdrant = qdrant
        self.embedder = embedder
        self.llm = llm
        self.collection = collection
        self.pil = pil or PILEnricher()
        self.graph = graph
        self._total_queries = 0
        self._total_latency = 0.0
        # Keyed by agent identifier; value = (seen_ids, last_touch_monotonic)
        self._agent_sessions: dict[str, tuple[set[str], float]] = {}

    # ==================== Intercept v2 Pipeline ====================

    async def intercept(self, request: InterceptRequest) -> InterceptResponseV2:
        """Process intercept through the v2 pipeline (backward-compatible)."""
        return await self.intercept_v2(request)

    async def intercept_v2(self, request: InterceptRequest) -> InterceptResponseV2:
        """Full v2 intercept pipeline.

        Flow: L1 read-only → redact → PIL → embed → parallel tier search →
              graph expand → rank → L3 LLM filter → cap → track.
        """
        trace_id = str(uuid.uuid4())
        start = time.monotonic()
        layers: list[str] = []

        # ── Layer 1: Read-only filter ──
        if self._is_readonly(request):
            layers.extend(["L1", "L1:skip"])
            return InterceptResponseV2(
                skipped=True, suggestions=[], latency_ms=0.0,
                layers_executed=layers, trace_id=trace_id,
            )
        layers.extend(["L1", "L1:pass"])

        # ── Redact secrets before any embedding/LLM call ──
        safe_action = redact_secrets(request.action)
        safe_request = request.model_copy(update={"action": safe_action})

        # ── PIL enrichment (≤200ms, fail-open) ──
        try:
            enriched = await asyncio.wait_for(self.pil.enrich(safe_request), timeout=0.2)
            layers.append("PIL")
        except (asyncio.TimeoutError, Exception):
            from src.domain.pil.pil_enricher import EnrichedPrompt
            enriched = EnrichedPrompt(
                original=safe_action, enriched=safe_action,
                intent="unknown", tags=[], confidence=0.0,
            )
            layers.append("PIL:fallback")

        # ── Embed enriched action (off the event loop — sentence-transformers is synchronous) ──
        try:
            loop = asyncio.get_running_loop()
            vec = await loop.run_in_executor(_SEARCH_POOL, self.embedder.embed, enriched.enriched)
        except Exception:
            logger.exception("Embedder failed")
            return InterceptResponseV2(
                skipped=False, suggestions=[], latency_ms=self._elapsed_ms(start),
                layers_executed=layers, trace_id=trace_id,
                intent=enriched.intent, enriched_action=enriched.enriched,
            )
        layers.append("EMBED")

        # ── Layer 2: Parallel multi-tier search ──
        try:
            all_hits = await self._parallel_tier_search(vec)
            layers.extend(["L2", "L2:T0+T1+T2"])
        except Exception:
            logger.exception("Layer 2 (Tier Search) failed")
            # Degraded mode: try v1 collection fallback
            try:
                all_hits = self.qdrant.search(self.collection, vec, top_k=10, score_threshold=0.3)
                # Normalize to tier-search format
                all_hits = [
                    {**h, "tier": h.get("payload", {}).get("tier", "t2_qa_cache")}
                    for h in all_hits
                ]
                layers.extend(["L2", "L2:v1-fallback"])
            except Exception:
                logger.exception("L2 v1 fallback also failed")
                return InterceptResponseV2(
                    skipped=False, suggestions=[], latency_ms=self._elapsed_ms(start),
                    layers_executed=layers, trace_id=trace_id,
                    intent=enriched.intent, enriched_action=enriched.enriched,
                )

        if not all_hits:
            self._record_query(start)
            return InterceptResponseV2(
                skipped=False, suggestions=[], latency_ms=self._elapsed_ms(start),
                layers_executed=layers, trace_id=trace_id,
                intent=enriched.intent, enriched_action=enriched.enriched,
            )

        # ── Graph expansion: 1-hop, capped at 8 ──
        if self.graph:
            try:
                candidate_ids = [str(h.get("id", "")) for h in all_hits if h.get("id")]
                expanded_ids = await self.graph.expand_1hop(candidate_ids)
                existing_ids = {str(h.get("id", "")) for h in all_hits}
                new_ids = [eid for eid in expanded_ids if eid not in existing_ids]
                if new_ids:
                    for nid in new_ids[:BUDGET_CAP]:
                        payload = self._fetch_any_tier(nid)
                        if payload:
                            all_hits.append({
                                "payload": payload, "score": 0.3,
                                "id": nid, "tier": payload.get("tier", "t2_qa_cache"),
                            })
                    layers.append("GRAPH")
            except Exception:
                logger.debug("Graph expansion failed (non-critical)")

        # ── Rank + dedup + budget cap ──
        candidates = [build_candidate_from_hit(h) for h in all_hits]
        ranked = rank(candidates, session_seen=self._get_session_seen(request.agent))
        ranked = ranked[:BUDGET_CAP]

        if not ranked:
            self._record_query(start)
            return InterceptResponseV2(
                skipped=False, suggestions=[], latency_ms=self._elapsed_ms(start),
                layers_executed=layers, trace_id=trace_id,
                intent=enriched.intent, enriched_action=enriched.enriched,
            )

        # ── Layer 3: LLM relevance filter (fail-open) ──
        suggestions = await self._llm_filter(ranked, enriched.enriched, safe_request.file_path, layers)

        # Cap at budget
        suggestions = suggestions[:BUDGET_CAP]

        # ── Track session seen + bump usage ──
        self._update_session_seen(request.agent, [s.experience_id for s in suggestions])

        # Async bump usage counters (fire-and-forget)
        asyncio.create_task(self._bump_usage_batch([s.experience_id for s in suggestions]))

        # Build tier breakdown
        suggestion_ids = {s.experience_id for s in suggestions}
        tier_breakdown: dict[str, int] = {}
        for c in ranked:
            if c.id in suggestion_ids:
                tier_breakdown[c.tier] = tier_breakdown.get(c.tier, 0) + 1

        self._record_query(start)
        return InterceptResponseV2(
            skipped=False,
            suggestions=suggestions,
            latency_ms=self._elapsed_ms(start),
            layers_executed=layers,
            trace_id=trace_id,
            intent=enriched.intent,
            enriched_action=enriched.enriched,
            tier_breakdown=tier_breakdown,
        )

    # ==================== Parallel search ====================

    async def _parallel_tier_search(self, vec: list[float]) -> list[dict[str, Any]]:
        """Search T0+T1 and T2 concurrently using thread pool for sync Qdrant calls."""
        loop = asyncio.get_event_loop()

        # Run T0+T1 and T2 searches in parallel threads
        t0t1_future = loop.run_in_executor(
            _SEARCH_POOL,
            lambda: self.qdrant.search_tiers(
                tiers=ALWAYS_LOAD_TIERS, vector=vec, top_k_per_tier=5,
            ),
        )
        t2_future = loop.run_in_executor(
            _SEARCH_POOL,
            lambda: self.qdrant.search_tiers(
                tiers=(KnowledgeTier.T2_QA_CACHE,), vector=vec, top_k_per_tier=5,
            ),
        )

        results_t0t1, results_t2 = await asyncio.gather(t0t1_future, t2_future)
        if not isinstance(results_t0t1, list) or not isinstance(results_t2, list):
            raise TypeError("search_tiers returned non-list (likely mock)")
        return results_t0t1 + results_t2

    # ==================== LLM filter ====================

    async def _llm_filter(
        self,
        ranked: list,
        enriched_text: str,
        file_path: str | None,
        layers: list[str],
    ) -> list[Suggestion]:
        """Layer 3: LLM relevance filter with degraded-mode fallback."""
        suggestions: list[Suggestion] = []

        # Check if LLM is available first (avoid slow timeout)
        llm_available = False
        try:
            llm_available = await asyncio.wait_for(self.llm.is_available(), timeout=1.0)
        except Exception:
            pass

        if llm_available:
            try:
                llm_input = [{"payload": c.payload, "score": c.score, "id": c.id} for c in ranked]
                relevant_ids = await asyncio.wait_for(
                    self.llm.filter_experiences(llm_input, enriched_text, file_path),
                    timeout=3.0,
                )
                layers.append("L3")

                for c in ranked:
                    if c.id in relevant_ids:
                        suggestions.append(self._to_suggestion(c, "llm_filter"))
                return suggestions
            except asyncio.TimeoutError:
                logger.warning("L3 LLM filter timed out; using semantic ranking (degraded)")
                layers.append("L3:timeout")
            except Exception:
                logger.exception("L3 filter error; using semantic ranking (degraded)")
                layers.append("L3:error")
        else:
            layers.append("L3:unavailable")

        # Degraded mode: return all ranked candidates without LLM filtering
        for c in ranked:
            suggestions.append(self._to_suggestion(c, "semantic_search"))
        return suggestions

    @staticmethod
    def _to_suggestion(candidate, source: str) -> Suggestion:
        """Convert a ranked candidate to a Suggestion."""
        return Suggestion(
            experience_id=candidate.id,
            title=candidate.payload.get("title", ""),
            message=candidate.payload.get("description", ""),
            severity=candidate.payload.get("severity", "info"),
            relevance_score=candidate.score,
            source=source,
        )

    # ==================== Usage tracking ====================

    async def _bump_usage_batch(self, experience_ids: list[str]) -> None:
        """Bump usage_count and last_used_at for surfaced experiences (fire-and-forget)."""
        now = datetime.now(timezone.utc).isoformat()
        for exp_id in experience_ids:
            for tier in KnowledgeTier:
                col = TIER_COLLECTION.get(tier)
                if not col:
                    continue
                try:
                    payload = self.qdrant.get_experience(col, exp_id)
                    if payload is None:
                        continue
                    current_usage = int(payload.get("usage_count", 0))
                    self.qdrant.client.set_payload(
                        collection_name=col,
                        payload={
                            "usage_count": current_usage + 1,
                            "last_used_at": now,
                        },
                        points=[exp_id],
                    )
                    break  # Found and updated
                except Exception:
                    continue

    # ==================== CRUD ====================

    def create_experience(self, request: CreateExperienceRequest) -> Experience:
        """Create a new experience and store it.

        v1 backward compat: defaults to T2_QA_CACHE tier and collection='experiences'.
        Also stores a copy in the T2 tier collection for v2 discoverability.
        """
        exp = Experience(
            id=str(uuid.uuid4()),
            title=request.title,
            description=request.description,
            category=request.category,
            tags=request.tags,
            file_patterns=request.file_patterns,
            language=request.language,
            severity=request.severity,
            tier=KnowledgeTier.T2_QA_CACHE,  # Task 14.4: v1 create → T2
        )

        text = f"{exp.title} {exp.description} {' '.join(exp.tags)}"
        vector = self.embedder.embed(text)

        # Store in v1 collection
        self.qdrant.upsert_experience(self.collection, exp, vector)

        # Also store in T2 tier collection for v2 pipeline
        t2_col = TIER_COLLECTION.get(KnowledgeTier.T2_QA_CACHE)
        if t2_col:
            try:
                self.qdrant.upsert_experience(t2_col, exp, vector)
            except Exception:
                logger.warning("Failed to replicate experience %s to T2 tier collection", exp.id)

        logger.info("Created experience: %s (%s) → T2", exp.id, exp.title)
        return exp

    def get_experience(self, exp_id: str) -> Experience | None:
        """Get a single experience by ID (searches v1 collection first, then tiers)."""
        # Try v1 collection
        data = self.qdrant.get_experience(self.collection, exp_id)
        if data:
            return Experience(**data)
        # Fallback: search tier collections
        payload = self._fetch_any_tier(exp_id)
        if payload:
            return Experience(**payload)
        return None

    def update_experience(self, exp_id: str, request: UpdateExperienceRequest) -> Experience | None:
        """Update an existing experience."""
        existing = self.get_experience(exp_id)
        if not existing:
            return None

        update_data = request.model_dump(exclude_none=True)
        updated = existing.model_copy(update=update_data)

        text = f"{updated.title} {updated.description} {' '.join(updated.tags)}"
        vector = self.embedder.embed(text)
        self.qdrant.upsert_experience(self.collection, updated, vector)

        # Sync to tier collection
        tier_col = TIER_COLLECTION.get(updated.tier)
        if tier_col:
            try:
                self.qdrant.upsert_experience(tier_col, updated, vector)
            except Exception:
                pass

        logger.info("Updated experience: %s", exp_id)
        return updated

    def delete_experience(self, exp_id: str) -> bool:
        """Delete an experience from v1 collection and tier collections."""
        deleted = False
        try:
            self.qdrant.delete_experience(self.collection, exp_id)
            deleted = True
        except Exception:
            pass

        # Also delete from tier collections
        for tier in KnowledgeTier:
            col = TIER_COLLECTION.get(tier)
            if col:
                try:
                    self.qdrant.delete_experience(col, exp_id)
                    deleted = True
                except Exception:
                    pass

        if deleted:
            logger.info("Deleted experience: %s", exp_id)
        return deleted

    def list_experiences(self, limit: int = 20, offset: int = 0) -> tuple[list[Experience], int]:
        """List experiences with pagination."""
        total = self.qdrant.count(self.collection)
        results = self.qdrant.list_experiences(self.collection, limit=limit, offset=offset)
        experiences = []
        for r in results:
            try:
                experiences.append(Experience(**r["payload"]))
            except Exception:
                continue
        return experiences, total

    def export_all(self) -> list[dict]:
        """Export ALL experiences as a list of dicts (for JSON backup)."""
        total = self.qdrant.count(self.collection)
        all_experiences = []
        batch_size = 100
        offset = 0

        while offset < total:
            results = self.qdrant.list_experiences(
                self.collection, limit=batch_size, offset=offset
            )
            for r in results:
                try:
                    exp = Experience(**r["payload"])
                    all_experiences.append(exp.model_dump(mode="json"))
                except Exception:
                    continue
            offset += batch_size

        logger.info("Exported %d experiences", len(all_experiences))
        return all_experiences

    def import_experiences(
        self, experiences: list[dict], *, overwrite: bool = False
    ) -> dict:
        """Import experiences from a list of dicts (from JSON backup)."""
        imported = 0
        skipped = 0
        failed = 0

        for exp_data in experiences:
            try:
                exp_id = exp_data.get("id", str(uuid.uuid4()))
                existing = self.get_experience(exp_id)
                if existing and not overwrite:
                    skipped += 1
                    continue

                exp = Experience(**exp_data)
                text = f"{exp.title} {exp.description} {' '.join(exp.tags)}"
                vector = self.embedder.embed(text)
                self.qdrant.upsert_experience(self.collection, exp, vector)
                imported += 1
            except Exception as e:
                logger.warning("Failed to import experience: %s", e)
                failed += 1

        logger.info(
            "Import complete: %d imported, %d skipped, %d failed",
            imported, skipped, failed,
        )
        return {
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "total_in_file": len(experiences),
        }

    def search_experiences(self, query: str, top_k: int = 10) -> list[Experience]:
        """Search experiences by text similarity."""
        vector = self.embedder.embed(query)
        results = self.qdrant.search(self.collection, vector, top_k=top_k, score_threshold=0.2)
        experiences = []
        for r in results:
            try:
                experiences.append(Experience(**r["payload"]))
            except Exception:
                continue
        return experiences

    def submit_feedback(self, exp_id: str, feedback: FeedbackRequest) -> bool:
        """Update feedback score and bump v2 counters.

        Task 14.3: v1 feedback maps to followed/ignored counter bumps.
        - score >= 0.5 → followed_count += 1
        - score <  0.5 → ignored_count += 1
        """
        exp = self.get_experience(exp_id)
        if not exp:
            return False

        # Exponential moving average for feedback
        exp.feedback_score = 0.7 * exp.feedback_score + 0.3 * feedback.score
        exp.usage_count += 1

        # Task 14.3: Map v1 feedback to v2 counters
        if feedback.score >= 0.5:
            exp.followed_count += 1
        else:
            exp.ignored_count += 1

        text = f"{exp.title} {exp.description} {' '.join(exp.tags)}"
        vector = self.embedder.embed(text)
        self.qdrant.upsert_experience(self.collection, exp, vector)

        # Sync counters to tier collection
        tier_col = TIER_COLLECTION.get(exp.tier)
        if tier_col:
            try:
                self.qdrant.client.set_payload(
                    collection_name=tier_col,
                    payload={
                        "followed_count": exp.followed_count,
                        "ignored_count": exp.ignored_count,
                        "usage_count": exp.usage_count,
                        "feedback_score": exp.feedback_score,
                    },
                    points=[exp_id],
                )
            except Exception:
                logger.debug("Failed to sync feedback to tier collection for %s", exp_id)

        return True

    # ==================== Stats ====================

    @property
    def total_queries(self) -> int:
        return self._total_queries

    @property
    def avg_latency_ms(self) -> float:
        if self._total_queries == 0:
            return 0.0
        return self._total_latency / self._total_queries

    def reset_session(self, agent: str | None = None) -> None:
        """Reset the session seen for a specific agent, or all sessions if agent is None."""
        if agent:
            self._agent_sessions.pop(agent, None)
        else:
            self._agent_sessions.clear()

    def _get_session_seen(self, agent: str | None) -> set[str]:
        """Return the active seen-set for this agent, creating a fresh one if TTL expired."""
        key = agent or "anonymous"
        now = time.monotonic()
        if key in self._agent_sessions:
            seen, ts = self._agent_sessions[key]
            if now - ts < _SESSION_TTL:
                return seen
        seen: set[str] = set()
        self._agent_sessions[key] = (seen, now)
        return seen

    def _update_session_seen(self, agent: str | None, ids: list[str]) -> None:
        """Add experience IDs to the agent's session dedup set and touch the TTL."""
        key = agent or "anonymous"
        now = time.monotonic()
        seen = self._get_session_seen(agent)
        seen.update(ids)
        self._agent_sessions[key] = (seen, now)
        # Prune stale sessions to prevent unbounded dict growth
        if len(self._agent_sessions) > 200:
            cutoff = now - _SESSION_TTL
            self._agent_sessions = {
                k: v for k, v in self._agent_sessions.items()
                if v[1] > cutoff
            }

    # ==================== Private ====================

    def _is_readonly(self, request: InterceptRequest) -> bool:
        """Check if the action is read-only using hardened tokenizer."""
        if request.action_type == ActionType.READ:
            return True
        if request.action_type in (ActionType.WRITE, ActionType.EXECUTE):
            return False
        return hardened_is_readonly(request.action)

    def _elapsed_ms(self, start: float) -> float:
        return (time.monotonic() - start) * 1000

    def _record_query(self, start: float) -> None:
        self._total_queries += 1
        self._total_latency += self._elapsed_ms(start)

    def _fetch_any_tier(self, exp_id: str) -> Optional[dict]:
        """Look up an experience by ID across all tier collections."""
        for tier in KnowledgeTier:
            col = TIER_COLLECTION.get(tier)
            if col:
                try:
                    payload = self.qdrant.get_experience(col, exp_id)
                    if payload:
                        return payload
                except Exception:
                    continue
        return None
