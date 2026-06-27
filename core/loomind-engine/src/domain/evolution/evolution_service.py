"""
Evolution Service — Promotes, demotes, abstracts experiences across tiers.

Algorithm 3 (run_cycle) and Algorithm 4 (abstract_cluster).
Requirements: 7.1–7.8
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.domain.evolution.tiers import TIER_COLLECTION, KnowledgeTier
from src.domain.models import EdgeType, EvolutionReport, Experience, Principle
from src.infrastructure.embedder import Embedder
from src.infrastructure.llm_client import LLMClient
from src.infrastructure.qdrant_client import QdrantStore

logger = logging.getLogger(__name__)

PROMOTE_THRESHOLD = 3
DEMOTE_THRESHOLD = 3
TIE_BREAKER_DELTA = 3
ABSTRACT_MIN_CLUSTER = 3
ABSTRACT_COSINE = 0.78
T3_TTL_DAYS = 30
CONFIDENCE_T2_TO_T1 = 0.7
MAX_RETRIES = 3


class EvolutionService:
    """Promotes / demotes / abstracts experiences across tiers."""

    def __init__(self, store: QdrantStore, embedder: Embedder, llm: LLMClient, graph: Any) -> None:
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.graph = graph

    async def run_cycle(self, batch_size: int = 100) -> EvolutionReport:
        start = time.monotonic()
        report = EvolutionReport()
        report.observations_consumed = await self._consume_observations(batch_size)
        report.pruned_t3_expired = await self._prune_t3()
        report.promoted_t3_to_t2 = await self._promote(KnowledgeTier.T3_RAW, KnowledgeTier.T2_QA_CACHE, None)
        report.promoted_t2_to_t1 = await self._promote(KnowledgeTier.T2_QA_CACHE, KnowledgeTier.T1_BEHAVIORAL, CONFIDENCE_T2_TO_T1)
        ids = await self._abstract_t1()
        report.abstracted_t1_to_t0 = len(ids)
        report.principle_ids = ids
        d1, d2 = await self._demote()
        report.demoted_t1_to_t2 = d1
        report.demoted_t2_to_t3 = d2
        report.duration_ms = (time.monotonic() - start) * 1000
        logger.info("Evolution cycle: %.1fms", report.duration_ms)
        return report

    async def _consume_observations(self, batch_size: int) -> int:
        """Fetch unprocessed judge observations, mark them consumed, return count.

        The actual followed_count / ignored_count on experiences are already bumped
        by JudgeService._bump_counter(). This method closes the audit loop so
        EvolutionReport reflects how many observations were available each cycle.
        """
        try:
            observations = self.store.get_unprocessed_observations(limit=batch_size)
        except Exception:
            logger.warning("Could not fetch observations; skipping consumption step")
            return 0
        if not observations:
            return 0
        obs_ids = [obs.id for obs in observations]
        self.store.mark_observations_processed(obs_ids)
        logger.info("Evolution cycle consumed %d observations", len(obs_ids))
        return len(obs_ids)

    async def _prune_t3(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=T3_TTL_DAYS)
        col = TIER_COLLECTION[KnowledgeTier.T3_RAW]
        pruned = 0
        for exp in self.store.scroll_tier(KnowledgeTier.T3_RAW):
            if exp.created_at <= cutoff and exp.followed_count < PROMOTE_THRESHOLD:
                try:
                    self.store.delete_experience(col, exp.id)
                    pruned += 1
                except Exception:
                    logger.exception("Prune fail %s", exp.id)
        return pruned

    async def _promote(self, src: KnowledgeTier, dst: KnowledgeTier, min_conf: float | None) -> int:
        src_col, dst_col = TIER_COLLECTION[src], TIER_COLLECTION[dst]
        count = 0
        for exp in self.store.scroll_tier(src):
            if exp.followed_count < PROMOTE_THRESHOLD:
                continue
            if min_conf is not None and exp.confidence < min_conf:
                continue
            if exp.ignored_count >= DEMOTE_THRESHOLD and (exp.followed_count - exp.ignored_count) < TIE_BREAKER_DELTA:
                continue
            try:
                new = exp.model_copy(update={"tier": dst})
                vec = self.embedder.embed(f"{new.title} {new.description} {' '.join(new.tags)}")
                self.store.upsert_experience(dst_col, new, vec)
                self._delete_retry(src_col, exp.id)
                count += 1
            except Exception:
                logger.exception("Promote fail %s", exp.id)
        return count

    async def _abstract_t1(self) -> list[str]:
        entries = list(self.store.scroll_tier(KnowledgeTier.T1_BEHAVIORAL))
        if len(entries) < ABSTRACT_MIN_CLUSTER:
            return []
        embs: dict[str, list[float]] = {}
        for e in entries:
            try:
                embs[e.id] = self.embedder.embed(f"{e.title} {e.description}")
            except Exception:
                continue
        clusters = self._cluster(entries, embs)
        ids: list[str] = []
        for cl in clusters:
            if len(cl) < ABSTRACT_MIN_CLUSTER:
                continue
            cl_ids = [e.id for e in cl]
            if self.store.query_edges(cl_ids, EdgeType.GENERALIZES):
                continue
            try:
                p = await self._abstract_one(cl)
                if p:
                    vec = self.embedder.embed(f"{p.title} {p.description}")
                    self.store.upsert_experience(TIER_COLLECTION[KnowledgeTier.T0_PRINCIPLE], p, vec)
                    for m in cl:
                        await self.graph.add_edge(src=p.id, dst=m.id, type=EdgeType.GENERALIZES)
                    ids.append(p.id)
            except Exception:
                logger.exception("Abstract fail")
        return ids

    async def _abstract_one(self, members: list[Experience]) -> Principle | None:
        bullets = "\n".join(f"- {m.title}: {m.description[:200]}" for m in members)
        prompt = f"Given these behavioral rules:\n{bullets}\n\nProduce ONE generalized principle.\nJSON: {{\"title\": \"..\", \"description\": \"..\", \"abstraction_summary\": \"..\", \"severity\": \"info|warning|critical\"}}"
        try:
            raw = await self.llm.complete(prompt, json_mode=True)
            spec = json.loads(raw)
        except Exception:
            spec = {"title": f"Principle from {len(members)} patterns", "description": "; ".join(m.title for m in members)[:300], "abstraction_summary": "Deterministic", "severity": "warning"}
        mean_conf = sum(m.confidence for m in members) / len(members)
        tags = list({t for m in members for t in m.tags})
        langs = [m.language for m in members if m.language]
        lang = max(set(langs), key=langs.count) if langs else None
        sev_map = {"info": 0, "warning": 1, "critical": 2}
        max_sev = max(members, key=lambda m: sev_map.get(m.severity.value, 0)).severity
        return Principle(id=str(uuid.uuid4()), title=spec.get("title", "Principle"), description=spec.get("description", ""), abstraction_summary=spec.get("abstraction_summary", ""), severity=spec.get("severity", max_sev.value), tier=KnowledgeTier.T0_PRINCIPLE, confidence=mean_conf, member_ids=[m.id for m in members], tags=tags, language=lang)

    async def _demote(self) -> tuple[int, int]:
        d1 = await self._demote_tier(KnowledgeTier.T1_BEHAVIORAL, KnowledgeTier.T2_QA_CACHE)
        d2 = await self._demote_tier(KnowledgeTier.T2_QA_CACHE, KnowledgeTier.T3_RAW)
        return d1, d2

    async def _demote_tier(self, src: KnowledgeTier, dst: KnowledgeTier) -> int:
        src_col, dst_col = TIER_COLLECTION[src], TIER_COLLECTION[dst]
        count = 0
        for exp in self.store.scroll_tier(src):
            if exp.ignored_count < DEMOTE_THRESHOLD:
                continue
            if exp.followed_count >= PROMOTE_THRESHOLD and (exp.ignored_count - exp.followed_count) < TIE_BREAKER_DELTA:
                continue
            try:
                new = exp.model_copy(update={"tier": dst})
                vec = self.embedder.embed(f"{new.title} {new.description} {' '.join(new.tags)}")
                self.store.upsert_experience(dst_col, new, vec)
                self._delete_retry(src_col, exp.id)
                count += 1
            except Exception:
                logger.exception("Demote fail %s", exp.id)
        return count

    def _delete_retry(self, col: str, eid: str) -> None:
        for i in range(MAX_RETRIES):
            try:
                self.store.delete_experience(col, eid)
                return
            except Exception:
                if i == MAX_RETRIES - 1:
                    logger.exception("Delete retry exhausted %s", eid)

    def _cluster(self, entries: list[Experience], embs: dict[str, list[float]]) -> list[list[Experience]]:
        used: set[str] = set()
        clusters: list[list[Experience]] = []
        for i, e in enumerate(entries):
            if e.id in used or e.id not in embs:
                continue
            cl = [e]
            used.add(e.id)
            for j in range(i + 1, len(entries)):
                o = entries[j]
                if o.id in used or o.id not in embs:
                    continue
                if self._cosine(embs[e.id], embs[o.id]) >= ABSTRACT_COSINE:
                    cl.append(o)
                    used.add(o.id)
            if len(cl) >= ABSTRACT_MIN_CLUSTER:
                clusters.append(cl)
        return clusters

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
