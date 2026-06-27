"""
Qdrant vector store client for the Experience Engine.
Supports both local (embedded) and server modes.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from src.domain.evolution.tiers import TIER_COLLECTION, KnowledgeTier
from src.domain.models import Edge, EdgeType, Experience, Observation

logger = logging.getLogger(__name__)

# Collection names
EDGES_COLLECTION = "exp_edges"
OBSERVATIONS_COLLECTION = "exp_observations"


class QdrantStore:
    """Wrapper around Qdrant client for experience vector storage."""

    def __init__(self, mode: str = "local", path: str = "./data/qdrant", url: str = "http://localhost:6333") -> None:
        self.mode = mode
        if mode == "local":
            logger.info("Initializing Qdrant in local (embedded) mode at: %s", path)
            self.client = QdrantClient(path=path)
        else:
            logger.info("Connecting to Qdrant server at: %s", url)
            self.client = QdrantClient(url=url)

    def ensure_collection(self, name: str, vector_size: int = 384) -> None:
        """Create collection if it doesn't exist."""
        collections = [c.name for c in self.client.get_collections().collections]
        if name not in collections:
            logger.info("Creating collection '%s' with vector_size=%d", name, vector_size)
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
        else:
            logger.info("Collection '%s' already exists", name)

    def upsert_experience(self, collection: str, experience: Experience, vector: list[float]) -> None:
        """Insert or update an experience with its embedding vector."""
        point = PointStruct(
            id=experience.id,
            vector=vector,
            payload=experience.model_dump(mode="json"),
        )
        self.client.upsert(collection_name=collection, points=[point])
        logger.debug("Upserted experience %s", experience.id)

    def search(
        self,
        collection: str,
        vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.3,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Search for similar experiences by vector."""
        query_filter = None
        if category:
            query_filter = Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            )

        results = self.client.query_points(
            collection_name=collection,
            query=vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )

        return [{"payload": hit.payload, "score": hit.score, "id": hit.id} for hit in results.points]

    def get_experience(self, collection: str, exp_id: str) -> Optional[dict[str, Any]]:
        """Get a single experience by ID."""
        try:
            results = self.client.retrieve(collection_name=collection, ids=[exp_id])
            if results:
                return results[0].payload
        except Exception:
            logger.exception("Failed to retrieve experience %s", exp_id)
        return None

    def delete_experience(self, collection: str, exp_id: str) -> None:
        """Delete an experience by ID."""
        self.client.delete(collection_name=collection, points_selector=[exp_id])
        logger.debug("Deleted experience %s", exp_id)

    def count(self, collection: str) -> int:
        """Count total experiences in collection."""
        info = self.client.get_collection(collection_name=collection)
        return info.points_count or 0

    def list_experiences(self, collection: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List experiences with pagination via scroll."""
        results, _ = self.client.scroll(collection_name=collection, limit=limit, offset=offset, with_payload=True)
        return [{"id": r.id, "payload": r.payload} for r in results]

    def is_healthy(self) -> bool:
        """Check if Qdrant is reachable."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the client connection."""
        try:
            self.client.close()
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════
    # Tier Collection Management (v2)
    # ══════════════════════════════════════════════════════════════════════

    def ensure_tier_collections(self, vector_size: int = 384) -> None:
        """Create all tier collections and the edges collection if they don't exist.

        Idempotent: skips creation for collections that already exist.
        Configures payload indexes on tier, language, category, superseded_by
        for tier collections and src_id, dst_id, type for the edges collection.

        Args:
            vector_size: Vector dimension size (default 384 for MiniLM).
        """
        existing = {c.name for c in self.client.get_collections().collections}

        # Create tier collections (exp_t0_principles, exp_t1_behavioral, exp_t2_qa_cache, exp_t3_raw)
        for tier, collection_name in TIER_COLLECTION.items():
            if collection_name not in existing:
                logger.info(
                    "Creating tier collection '%s' (tier=%s, vector_size=%d, distance=COSINE)",
                    collection_name,
                    tier.value,
                    vector_size,
                )
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                # Create payload indexes for tier collections
                for field_name in ("tier", "language", "category", "superseded_by"):
                    self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_name,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )
                logger.info("Created collection '%s' with payload indexes", collection_name)
            else:
                logger.info("Tier collection '%s' already exists, skipping", collection_name)

        # Create edges collection (placeholder vector, never vector-searched)
        if EDGES_COLLECTION not in existing:
            logger.info("Creating edges collection '%s'", EDGES_COLLECTION)
            self.client.create_collection(
                collection_name=EDGES_COLLECTION,
                vectors_config=VectorParams(size=1, distance=Distance.COSINE),
            )
            # Create payload indexes for edges
            for field_name in ("src_id", "dst_id", "type"):
                self.client.create_payload_index(
                    collection_name=EDGES_COLLECTION,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            logger.info("Created edges collection '%s' with payload indexes", EDGES_COLLECTION)
        else:
            logger.info("Edges collection '%s' already exists, skipping", EDGES_COLLECTION)

    def search_tiers(
        self,
        tiers: tuple[KnowledgeTier, ...],
        vector: list[float],
        top_k_per_tier: int = 5,
        filters: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Search multiple tier collections in parallel-style (sequential for now).

        Searches each specified tier collection and aggregates results.
        Applies tier-specific score thresholds:
        - T0, T1: min score 0.30
        - T2: min score 0.55
        - T3: never searched (excluded by design)

        Args:
            tiers: Tuple of tiers to search.
            vector: Query embedding vector.
            top_k_per_tier: Max results per tier (default 5).
            filters: Optional payload filters (e.g., {"language": "python"}).

        Returns:
            List of scored points with payload, score, id, and tier info.
        """
        results: list[dict[str, Any]] = []

        for tier in tiers:
            # Never search T3 (raw/staging) — Requirement 2.4
            if tier == KnowledgeTier.T3_RAW:
                continue

            collection_name = TIER_COLLECTION.get(tier)
            if not collection_name:
                continue

            # Tier-specific score thresholds per Requirement 2.3
            if tier in (KnowledgeTier.T0_PRINCIPLE, KnowledgeTier.T1_BEHAVIORAL):
                score_threshold = 0.30
            else:  # T2_QA_CACHE
                score_threshold = 0.55

            # Build query filter
            query_filter = self._build_filter(filters) if filters else None

            try:
                search_results = self.client.query_points(
                    collection_name=collection_name,
                    query=vector,
                    limit=top_k_per_tier,
                    score_threshold=score_threshold,
                    query_filter=query_filter,
                )

                for hit in search_results.points:
                    results.append({
                        "payload": hit.payload,
                        "score": hit.score,
                        "id": hit.id,
                        "tier": tier.value,
                    })
            except Exception:
                logger.exception("Failed to search tier collection '%s'", collection_name)

        return results

    def upsert_edge(self, edge: Edge) -> None:
        """Insert or update an edge in the edges collection.

        Args:
            edge: The Edge model instance to upsert.
        """
        point = PointStruct(
            id=edge.id,
            vector=[0.0],  # Placeholder vector — edges are never vector-searched
            payload=edge.model_dump(mode="json"),
        )
        self.client.upsert(collection_name=EDGES_COLLECTION, points=[point])
        logger.debug("Upserted edge %s (%s -> %s, type=%s)", edge.id, edge.src_id, edge.dst_id, edge.type)

    def query_edges(
        self,
        src_or_dst_ids: list[str],
        type: EdgeType | None = None,
    ) -> list[Edge]:
        """Query edges by source or destination IDs, optionally filtered by type.

        Args:
            src_or_dst_ids: List of experience IDs to match as src_id OR dst_id.
            type: Optional edge type filter.

        Returns:
            List of Edge model instances matching the query.
        """
        edges: list[Edge] = []

        for exp_id in src_or_dst_ids:
            # Query edges where this ID is the source
            src_filter = Filter(
                must=[FieldCondition(key="src_id", match=MatchValue(value=exp_id))]
            )
            if type is not None:
                src_filter.must.append(
                    FieldCondition(key="type", match=MatchValue(value=type.value))
                )

            # Query edges where this ID is the destination
            dst_filter = Filter(
                must=[FieldCondition(key="dst_id", match=MatchValue(value=exp_id))]
            )
            if type is not None:
                dst_filter.must.append(
                    FieldCondition(key="type", match=MatchValue(value=type.value))
                )

            try:
                # Scroll src matches
                src_results, _ = self.client.scroll(
                    collection_name=EDGES_COLLECTION,
                    scroll_filter=src_filter,
                    limit=100,
                    with_payload=True,
                )
                for point in src_results:
                    if point.payload:
                        edges.append(Edge(**point.payload))

                # Scroll dst matches
                dst_results, _ = self.client.scroll(
                    collection_name=EDGES_COLLECTION,
                    scroll_filter=dst_filter,
                    limit=100,
                    with_payload=True,
                )
                for point in dst_results:
                    if point.payload:
                        edges.append(Edge(**point.payload))
            except Exception:
                logger.exception("Failed to query edges for ID '%s'", exp_id)

        # Deduplicate by edge ID
        seen_ids: set[str] = set()
        unique_edges: list[Edge] = []
        for edge in edges:
            if edge.id not in seen_ids:
                seen_ids.add(edge.id)
                unique_edges.append(edge)

        return unique_edges

    def scroll_tier(
        self,
        tier: KnowledgeTier,
        since: datetime | None = None,
    ) -> Iterator[Experience]:
        """Scroll through all experiences in a tier collection.

        Optionally filters by creation date (since). Yields Experience instances.

        Args:
            tier: The knowledge tier to scroll.
            since: Optional datetime filter — only return experiences created after this time.

        Yields:
            Experience model instances from the tier collection.
        """
        collection_name = TIER_COLLECTION.get(tier)
        if not collection_name:
            return

        offset = None
        batch_size = 100

        while True:
            try:
                results, next_offset = self.client.scroll(
                    collection_name=collection_name,
                    limit=batch_size,
                    offset=offset,
                    with_payload=True,
                )
            except Exception:
                logger.exception("Failed to scroll tier collection '%s'", collection_name)
                return

            if not results:
                return

            for point in results:
                if point.payload:
                    try:
                        experience = Experience(**point.payload)
                        # Apply since filter if provided
                        if since is not None and experience.created_at <= since:
                            continue
                        yield experience
                    except Exception:
                        logger.warning("Failed to parse experience from point %s", point.id)

            if next_offset is None:
                return
            offset = next_offset

    # ══════════════════════════════════════════════════════════════════════
    # Observation Store (Phase 9A — closed-loop feedback persistence)
    # ══════════════════════════════════════════════════════════════════════

    def ensure_observations_collection(self) -> None:
        """Create the observations collection if it doesn't exist."""
        existing = {c.name for c in self.client.get_collections().collections}
        if OBSERVATIONS_COLLECTION not in existing:
            self.client.create_collection(
                collection_name=OBSERVATIONS_COLLECTION,
                vectors_config=VectorParams(size=1, distance=Distance.COSINE),
            )
            for field_name in ("experience_id", "verdict", "processed_by_evolution"):
                self.client.create_payload_index(
                    collection_name=OBSERVATIONS_COLLECTION,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            logger.info("Created observations collection '%s'", OBSERVATIONS_COLLECTION)

    def store_observation(self, obs: Observation) -> None:
        """Persist a judge observation for later consumption by the evolution cycle."""
        point = PointStruct(
            id=obs.id,
            vector=[0.0],
            payload=obs.model_dump(mode="json"),
        )
        self.client.upsert(collection_name=OBSERVATIONS_COLLECTION, points=[point])

    def get_unprocessed_observations(self, limit: int = 100) -> list[Observation]:
        """Return observations not yet consumed by an evolution cycle."""
        try:
            results, _ = self.client.scroll(
                collection_name=OBSERVATIONS_COLLECTION,
                scroll_filter=Filter(
                    must=[FieldCondition(key="processed_by_evolution", match=MatchValue(value=False))]
                ),
                limit=limit,
                with_payload=True,
            )
            observations = []
            for point in results:
                if point.payload:
                    try:
                        observations.append(Observation(**point.payload))
                    except Exception:
                        logger.warning("Skipping malformed observation %s", point.id)
            return observations
        except Exception:
            logger.exception("Failed to fetch unprocessed observations")
            return []

    def mark_observations_processed(self, obs_ids: list[str]) -> None:
        """Mark a batch of observations as consumed by the evolution cycle."""
        if not obs_ids:
            return
        try:
            self.client.set_payload(
                collection_name=OBSERVATIONS_COLLECTION,
                payload={"processed_by_evolution": True},
                points=obs_ids,
            )
        except Exception:
            logger.exception("Failed to mark %d observations as processed", len(obs_ids))

    # ══════════════════════════════════════════════════════════════════════
    # Private helpers
    # ══════════════════════════════════════════════════════════════════════

    def _build_filter(self, filters: dict) -> Filter | None:
        """Build a Qdrant Filter from a dict of field conditions.

        Supports simple key-value matching on payload fields.
        """
        if not filters:
            return None

        conditions = []
        for key, value in filters.items():
            if value is not None:
                conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))

        if not conditions:
            return None

        return Filter(must=conditions)
