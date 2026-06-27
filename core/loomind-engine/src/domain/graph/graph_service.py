"""
Graph Service — Experience knowledge graph and temporal reasoning.

Provides typed edges (`generalizes`, `relates_to`, `supersedes`) between
experiences stored across tiered Qdrant collections. The graph is an adjacency
list living in the `exp_edges` collection (no separate graph DB needed).

Public surface:
  - add_edge(src, dst, type, weight)       — upsert a typed edge
  - expand_1hop(ids)                       — return ids ∪ top-8 neighbors
  - supersede(old_id, new_id)              — mark old as superseded; add SUPERSEDES edge
  - supersede_on_conflict(new_exp, ...)    — auto-detect contradicting older entry and supersede it
  - timeline(topic)                        — reverse-chronological supersession chain (max 50)

Design references:
  - design.md → "Components and Interfaces" → GraphService
  - design.md → "Algorithm 8 — Supersession on conflict"
  - Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from src.domain.evolution.tiers import TIER_COLLECTION, KnowledgeTier
from src.domain.models import Edge, EdgeType, Experience, TimelineEntry
from src.infrastructure.qdrant_client import QdrantStore

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# Supersession-on-conflict tunables (Algorithm 8 — Requirements 4.3, 4.4)
# ─────────────────────────────────────────────────────────────────────────

# Cosine similarity bar for considering an older entry a candidate for
# supersession. Intentionally high so we only invoke the LLM on strongly
# overlapping experiences.
SUPERSEDE_COSINE_THRESHOLD: float = 0.85

# Maximum total time (seconds) we allow the LLM to confirm a single
# contradiction. Beyond this we fail-open and skip supersession.
LLM_CONTRADICTION_TIMEOUT: float = 3.0

# Tiers searched for supersession candidates. T3 is excluded by design so
# raw/staging entries cannot be superseded (and cannot supersede curated
# tiers). Mirrors the always-load + cache tiers used by intercept.
SUPERSEDE_SEARCH_TIERS: tuple[KnowledgeTier, ...] = (
    KnowledgeTier.T0_PRINCIPLE,
    KnowledgeTier.T1_BEHAVIORAL,
    KnowledgeTier.T2_QA_CACHE,
)


# Tier search order for supersede() — prefer most-curated tiers first
SUPERSEDE_TIER_ORDER: tuple[KnowledgeTier, ...] = (
    KnowledgeTier.T0_PRINCIPLE,
    KnowledgeTier.T1_BEHAVIORAL,
    KnowledgeTier.T2_QA_CACHE,
    KnowledgeTier.T3_RAW,
)

# Maximum neighbors returned by 1-hop expansion (Requirement 4.2)
MAX_NEIGHBORS: int = 8

# Score threshold for timeline topic search across always-loaded tiers
TIMELINE_SCORE_THRESHOLD: float = 0.60

# Maximum entries returned by timeline()
TIMELINE_MAX_ENTRIES: int = 50

# Tiers searched by timeline() — T3 is excluded (raw/staging)
TIMELINE_TIERS: tuple[KnowledgeTier, ...] = (
    KnowledgeTier.T0_PRINCIPLE,
    KnowledgeTier.T1_BEHAVIORAL,
    KnowledgeTier.T2_QA_CACHE,
)

# Cosine threshold for declaring two experiences similar enough to potentially
# conflict (Algorithm 8). High bar to avoid false positives.
SUPERSEDE_COSINE_THRESHOLD: float = 0.85

# Tiers scanned for supersession candidates (T3 is staging — never supersedes)
SUPERSEDE_SCAN_TIERS: tuple[KnowledgeTier, ...] = (
    KnowledgeTier.T0_PRINCIPLE,
    KnowledgeTier.T1_BEHAVIORAL,
    KnowledgeTier.T2_QA_CACHE,
)

# Hard timeout for the LLM contradiction confirmation call (Requirement 4.4).
LLM_CONTRADICTION_TIMEOUT: float = 3.0

# Maximum number of contradiction-candidates the LLM will judge per call.
SUPERSEDE_MAX_CANDIDATES: int = 5


class GraphService:
    """Manages the experience knowledge graph (typed edges + traversal).

    Edges are persisted in the `exp_edges` Qdrant collection via QdrantStore.
    All methods are async to keep the public surface uniform with the rest of
    the v2 service layer, even when the underlying I/O is synchronous.
    """

    def __init__(self, qdrant: QdrantStore, embedder: Optional[Any] = None) -> None:
        """Initialize the graph service.

        Args:
            qdrant: QdrantStore for edge persistence and tier collection access.
            embedder: Optional embedder used by `timeline()` to vectorize topics.
                Required for `timeline()`; other methods do not need it.
        """
        self.qdrant = qdrant
        self.embedder = embedder

    # ══════════════════════════════════════════════════════════════════════
    # Edge management
    # ══════════════════════════════════════════════════════════════════════

    async def add_edge(
        self,
        src: str,
        dst: str,
        type: EdgeType,
        weight: float = 1.0,
    ) -> Edge:
        """Create and persist a typed edge from `src` to `dst`.

        Args:
            src: Source experience ID.
            dst: Destination experience ID.
            type: Edge type (GENERALIZES, RELATES_TO, SUPERSEDES).
            weight: Edge weight in [0.0, 1.0]. Defaults to 1.0.

        Returns:
            The persisted Edge instance (with auto-generated id and created_at).
        """
        edge = Edge(src_id=src, dst_id=dst, type=type, weight=weight)
        self.qdrant.upsert_edge(edge)
        logger.info(
            "Added edge %s: %s -[%s w=%.2f]-> %s",
            edge.id,
            src,
            type.value,
            weight,
            dst,
        )
        return edge

    # ══════════════════════════════════════════════════════════════════════
    # 1-hop expansion (used by intercept ranker)
    # ══════════════════════════════════════════════════════════════════════

    async def expand_1hop(self, ids: list[str]) -> list[str]:
        """Expand a set of experience IDs with their 1-hop neighbors.

        For each input ID, fetch all incident edges (as src or dst) and collect
        the *other* endpoint as a neighbor. Neighbors are deduplicated, ranked
        by edge weight (descending), and capped at `MAX_NEIGHBORS` (8).

        Returns the union of input IDs and the top neighbors. Input IDs always
        come first in the returned list to preserve seed ordering.

        Args:
            ids: Seed experience IDs to expand.

        Returns:
            List of IDs containing the original seeds plus up to 8 unique
            neighbors. Returns the seeds unchanged when `ids` is empty or when
            no edges are incident on any seed.
        """
        if not ids:
            return []

        seed_set = set(ids)

        try:
            edges = self.qdrant.query_edges(src_or_dst_ids=ids)
        except Exception:
            logger.exception("Failed to query edges for expand_1hop; returning seeds only")
            return list(ids)

        # Track best edge weight per neighbor for ranking
        neighbor_weights: dict[str, float] = {}
        for edge in edges:
            # The neighbor is whichever endpoint is NOT one of our seeds.
            # If both endpoints are seeds (intra-seed edge), skip — it adds nothing.
            if edge.src_id in seed_set and edge.dst_id not in seed_set:
                neighbor = edge.dst_id
            elif edge.dst_id in seed_set and edge.src_id not in seed_set:
                neighbor = edge.src_id
            else:
                continue

            # Keep the maximum weight seen for this neighbor
            existing = neighbor_weights.get(neighbor, 0.0)
            if edge.weight > existing:
                neighbor_weights[neighbor] = edge.weight

        # Sort neighbors by weight descending, then by ID for deterministic ordering
        ranked_neighbors = sorted(
            neighbor_weights.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )
        top_neighbors = [nid for nid, _ in ranked_neighbors[:MAX_NEIGHBORS]]

        result = list(ids) + top_neighbors
        logger.debug(
            "expand_1hop: %d seeds → %d neighbors (capped at %d)",
            len(ids),
            len(top_neighbors),
            MAX_NEIGHBORS,
        )
        return result

    # ══════════════════════════════════════════════════════════════════════
    # Supersession
    # ══════════════════════════════════════════════════════════════════════

    async def supersede(self, old_id: str, new_id: str) -> None:
        """Mark `old_id` as superseded by `new_id` and record a SUPERSEDES edge.

        Searches every tier collection (T0 → T1 → T2 → T3) until the old
        experience is located, then patches its payload with `superseded_by`.
        Once the old entry is updated (or if it cannot be found), creates a
        SUPERSEDES edge from the new experience to the old one so timeline
        traversal can walk the chain.

        Args:
            old_id: The experience being superseded.
            new_id: The replacement experience.
        """
        if old_id == new_id:
            logger.warning("supersede() called with old_id == new_id (%s); skipping", old_id)
            return

        located_tier: Optional[str] = None

        for tier in SUPERSEDE_TIER_ORDER:
            collection = TIER_COLLECTION[tier]
            try:
                payload = self.qdrant.get_experience(collection, old_id)
            except Exception:
                logger.exception(
                    "Failed to query collection '%s' for old_id=%s",
                    collection,
                    old_id,
                )
                continue

            if payload is None:
                continue

            # Found it — patch the superseded_by field in place.
            try:
                self.qdrant.client.set_payload(
                    collection_name=collection,
                    payload={"superseded_by": new_id},
                    points=[old_id],
                )
                located_tier = collection
                logger.info(
                    "Marked %s as superseded_by=%s in collection '%s'",
                    old_id,
                    new_id,
                    collection,
                )
                break
            except Exception:
                logger.exception(
                    "Failed to patch superseded_by on %s in '%s'",
                    old_id,
                    collection,
                )
                # Continue to next tier in case of transient failure on this one.
                continue

        if located_tier is None:
            logger.warning(
                "supersede(): could not locate experience %s in any tier; "
                "creating SUPERSEDES edge anyway for forward consistency",
                old_id,
            )

        # Always add the SUPERSEDES edge so the supersession is queryable.
        await self.add_edge(src=new_id, dst=old_id, type=EdgeType.SUPERSEDES)

    # ══════════════════════════════════════════════════════════════════════
    # Timeline (reverse-chronological supersession walk)
    # ══════════════════════════════════════════════════════════════════════

    async def timeline(self, topic: str) -> list[TimelineEntry]:
        """Build a reverse-chronological timeline for a topic.

        Embeds the topic, searches T0/T1/T2 with score threshold 0.60, then
        walks SUPERSEDES edges from each seed result to collect the full
        supersession chain. Entries are deduplicated by experience_id, sorted
        by `created_at` descending, and capped at 50.

        Args:
            topic: Free-text topic to search for (e.g., "dependency injection").

        Returns:
            Up to 50 TimelineEntry items, newest first. Returns an empty list
            when the embedder is unavailable or no matching experiences exist.
        """
        if self.embedder is None:
            logger.warning("timeline() called without an embedder; returning empty list")
            return []

        topic_clean = (topic or "").strip()
        if not topic_clean:
            logger.debug("timeline() called with empty topic; returning empty list")
            return []

        # 1. Embed the topic
        try:
            vector = self.embedder.embed(topic_clean)
        except Exception:
            logger.exception("timeline(): embedder failed for topic=%r", topic_clean)
            return []

        # 2. Search across T0/T1/T2 with the timeline-specific threshold.
        #    QdrantStore.search_tiers applies its own per-tier thresholds, so
        #    we filter again here against TIMELINE_SCORE_THRESHOLD (0.60) for
        #    a uniform topic-match bar across all tiers.
        try:
            scored = self.qdrant.search_tiers(
                tiers=TIMELINE_TIERS,
                vector=vector,
                top_k_per_tier=TIMELINE_MAX_ENTRIES,
            )
        except Exception:
            logger.exception("timeline(): tier search failed for topic=%r", topic_clean)
            return []

        # Apply uniform threshold and seed the timeline
        seed_payloads: dict[str, dict[str, Any]] = {}
        for hit in scored:
            score = hit.get("score", 0.0)
            if score < TIMELINE_SCORE_THRESHOLD:
                continue
            payload = hit.get("payload")
            exp_id = hit.get("id")
            if not payload or not exp_id:
                continue
            # Keep the highest-scoring payload per experience_id
            if exp_id not in seed_payloads:
                seed_payloads[str(exp_id)] = payload

        if not seed_payloads:
            logger.debug("timeline(): no seeds passed threshold for topic=%r", topic_clean)
            return []

        # 3. Walk SUPERSEDES edges from each seed to collect the chain.
        entries: dict[str, Experience] = {}
        for exp_id, payload in seed_payloads.items():
            try:
                exp = Experience(**payload)
            except Exception:
                logger.warning("timeline(): failed to parse experience %s", exp_id)
                continue
            entries[exp.id] = exp

        await self._walk_supersedes(list(entries.keys()), entries)

        # 4. Build TimelineEntry items, sort reverse-chronologically, cap at 50.
        timeline_entries = [
            TimelineEntry(
                experience_id=exp.id,
                title=exp.title,
                summary=self._summarize(exp),
                confidence=exp.confidence,
                superseded=exp.superseded_by is not None,
                superseded_by=exp.superseded_by,
                created_at=exp.created_at,
            )
            for exp in entries.values()
        ]
        timeline_entries.sort(key=lambda e: e.created_at, reverse=True)
        timeline_entries = timeline_entries[:TIMELINE_MAX_ENTRIES]

        logger.info(
            "timeline(topic=%r): %d entries (after walk + cap)",
            topic_clean,
            len(timeline_entries),
        )
        return timeline_entries

    # ══════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ══════════════════════════════════════════════════════════════════════

    async def _walk_supersedes(
        self,
        seed_ids: list[str],
        collected: dict[str, Experience],
    ) -> None:
        """Breadth-first walk over SUPERSEDES edges, mutating `collected` in place.

        For each seed, follows both directions (newer→older and older→newer)
        so the timeline contains the full chain regardless of which member the
        topic search originally hit. Stops when the collected set hits the
        TIMELINE_MAX_ENTRIES cap to avoid unbounded traversal.
        """
        frontier: list[str] = list(seed_ids)
        visited: set[str] = set(seed_ids)

        while frontier and len(collected) < TIMELINE_MAX_ENTRIES:
            try:
                edges = self.qdrant.query_edges(
                    src_or_dst_ids=frontier,
                    type=EdgeType.SUPERSEDES,
                )
            except Exception:
                logger.exception("timeline(): query_edges failed during walk")
                return

            next_frontier: list[str] = []
            for edge in edges:
                for endpoint in (edge.src_id, edge.dst_id):
                    if endpoint in visited:
                        continue
                    visited.add(endpoint)

                    exp = self._fetch_any_tier(endpoint)
                    if exp is not None:
                        collected[exp.id] = exp
                        next_frontier.append(endpoint)
                        if len(collected) >= TIMELINE_MAX_ENTRIES:
                            return

            frontier = next_frontier

    def _fetch_any_tier(self, exp_id: str) -> Optional[Experience]:
        """Look up an experience by ID across all tier collections.

        Returns the first match or None if the ID is not found anywhere.
        """
        for tier in SUPERSEDE_TIER_ORDER:
            collection = TIER_COLLECTION[tier]
            try:
                payload = self.qdrant.get_experience(collection, exp_id)
            except Exception:
                logger.exception(
                    "_fetch_any_tier: error reading '%s' for %s",
                    collection,
                    exp_id,
                )
                continue

            if payload is None:
                continue

            try:
                return Experience(**payload)
            except Exception:
                logger.warning(
                    "_fetch_any_tier: failed to parse experience %s from '%s'",
                    exp_id,
                    collection,
                )
                return None
        return None

    @staticmethod
    def _summarize(exp: Experience) -> str:
        """Produce a brief summary suitable for TimelineEntry.summary.

        Truncates `description` at 200 characters with an ellipsis when longer.
        """
        desc = exp.description or ""
        if len(desc) <= 200:
            return desc
        return desc[:197].rstrip() + "..."

    # ══════════════════════════════════════════════════════════════════════
    # Supersession on conflict (Algorithm 8)
    # ══════════════════════════════════════════════════════════════════════

    async def supersede_on_conflict(
        self,
        new_exp: Experience,
        *,
        embedder: Optional[Any] = None,
        llm: Optional[Any] = None,
    ) -> Optional[str]:
        """Detect and supersede an existing experience that contradicts ``new_exp``.

        Algorithm 8 (design.md):
          1. Embed ``new_exp`` and search T0/T1/T2 for candidates with cosine ≥ 0.85
          2. Skip candidates already superseded or whose id matches ``new_exp.id``
          3. For each candidate (up to ``SUPERSEDE_MAX_CANDIDATES``), ask the LLM
             whether ``new_exp`` contradicts the candidate. The LLM call is
             bounded by ``LLM_CONTRADICTION_TIMEOUT`` (3 seconds) via
             ``asyncio.wait_for``.
          4. On the first confirmed contradiction, call :meth:`supersede` to
             mark the candidate ``superseded_by=new_exp.id`` and add a
             ``SUPERSEDES`` edge. Return the candidate id.
          5. Otherwise return ``None``.

        Fail-open behavior (Requirement 4.4):
          - If ``embedder`` is None or the embed call fails → return None.
          - If ``llm`` is None or the LLM call times out / errors → return None
            without performing supersession.
          - If JSON parsing of the LLM response fails → treat as "no contradiction"
            and continue with the next candidate.

        Args:
            new_exp: The freshly-created experience to check.
            embedder: Optional embedder used to vectorize ``new_exp``.
            llm: Optional LLM client; must expose ``async complete(prompt) -> str``.

        Returns:
            The id of the experience that was marked superseded, or ``None``.
        """
        if embedder is None:
            logger.debug("supersede_on_conflict: no embedder provided; skipping")
            return None
        if llm is None:
            logger.debug("supersede_on_conflict: no LLM provided; skipping")
            return None

        # 1. Embed the new experience
        embed_text = f"{new_exp.title}\n{new_exp.description}".strip()
        if not embed_text:
            logger.debug("supersede_on_conflict: new_exp has empty title/description")
            return None

        try:
            vector = embedder.embed(embed_text)
        except Exception:
            logger.exception("supersede_on_conflict: embedder failed for %s", new_exp.id)
            return None

        # 2. Search T0/T1/T2 for similarity candidates
        try:
            scored = self.qdrant.search_tiers(
                tiers=SUPERSEDE_SCAN_TIERS,
                vector=vector,
                top_k_per_tier=SUPERSEDE_MAX_CANDIDATES,
            )
        except Exception:
            logger.exception(
                "supersede_on_conflict: tier search failed for %s", new_exp.id
            )
            return None

        # 3. Filter candidates by cosine threshold and skip self / already-superseded
        candidates: list[Experience] = []
        for hit in scored:
            score = hit.get("score", 0.0)
            if score < SUPERSEDE_COSINE_THRESHOLD:
                continue
            payload = hit.get("payload")
            if not payload:
                continue
            try:
                candidate = Experience(**payload)
            except Exception:
                logger.warning(
                    "supersede_on_conflict: failed to parse candidate payload"
                )
                continue
            if candidate.id == new_exp.id:
                continue
            if candidate.superseded_by is not None:
                # Already superseded — skip; we don't supersede a chain head twice.
                continue
            candidates.append(candidate)
            if len(candidates) >= SUPERSEDE_MAX_CANDIDATES:
                break

        if not candidates:
            logger.debug(
                "supersede_on_conflict: no high-similarity candidates for %s",
                new_exp.id,
            )
            return None

        # 4. Ask the LLM whether new_exp contradicts each candidate (bounded total time)
        deadline = asyncio.get_event_loop().time() + LLM_CONTRADICTION_TIMEOUT
        for candidate in candidates:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning(
                    "supersede_on_conflict: LLM budget exhausted before judging %s; "
                    "skipping (fail-open)",
                    candidate.id,
                )
                return None

            prompt = self._build_contradiction_prompt(candidate, new_exp)
            try:
                response_text = await asyncio.wait_for(
                    llm.complete(prompt), timeout=remaining
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "supersede_on_conflict: LLM timed out judging %s vs %s "
                    "(fail-open, skipping)",
                    candidate.id,
                    new_exp.id,
                )
                return None
            except Exception:
                logger.exception(
                    "supersede_on_conflict: LLM error judging %s vs %s "
                    "(fail-open, skipping)",
                    candidate.id,
                    new_exp.id,
                )
                return None

            verdict = self._parse_contradiction_response(response_text)
            if verdict is True:
                logger.info(
                    "supersede_on_conflict: LLM confirmed contradiction; "
                    "%s supersedes %s",
                    new_exp.id,
                    candidate.id,
                )
                await self.supersede(old_id=candidate.id, new_id=new_exp.id)
                return candidate.id

        logger.debug(
            "supersede_on_conflict: LLM found no contradictions among %d candidate(s)",
            len(candidates),
        )
        return None

    @staticmethod
    def _build_contradiction_prompt(old: Experience, new_exp: Experience) -> str:
        """Render the JSON-only contradiction prompt for the LLM."""
        return (
            "Two experiences may contradict each other. Reply with JSON only.\n\n"
            "EXISTING:\n"
            f"Title: {old.title}\n"
            f"Description: {old.description}\n\n"
            "NEW:\n"
            f"Title: {new_exp.title}\n"
            f"Description: {new_exp.description}\n\n"
            "Does the NEW experience CONTRADICT the EXISTING one? "
            'Reply JSON only:\n{"contradicts": true|false, "reason": "<short reason>"}'
        )

    @staticmethod
    def _parse_contradiction_response(response_text: str) -> Optional[bool]:
        """Parse the LLM JSON response. Returns ``contradicts`` boolean or None.

        On any parse failure, returns None which the caller treats as
        "no contradiction" (fail-open).
        """
        if not response_text:
            return None
        try:
            data = json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            logger.debug(
                "supersede_on_conflict: could not parse LLM JSON: %r",
                response_text[:200],
            )
            return None
        value = data.get("contradicts")
        if isinstance(value, bool):
            return value
        return None
