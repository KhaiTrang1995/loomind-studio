"""Knowledge tier definitions and collection mappings.

Defines the 4-tier knowledge architecture:
- T0 Principles: always-loaded, generalized rules abstracted from clusters
- T1 Behavioral: always-loaded, confirmed reflexes (followed ≥3 times)
- T2 QA Cache: retrieved on semantic match, default tier for new experiences
- T3 Raw: staging tier with 30-day TTL, may be noisy
"""

from enum import Enum


class KnowledgeTier(str, Enum):
    """Four-tier knowledge classification for experiences."""

    T0_PRINCIPLE = "t0_principle"  # always-loaded, generalized rules
    T1_BEHAVIORAL = "t1_behavioral"  # always-loaded, confirmed reflexes
    T2_QA_CACHE = "t2_qa_cache"  # retrieved on semantic match
    T3_RAW = "t3_raw"  # staging, TTL 30d, may be noisy


TIER_COLLECTION: dict[KnowledgeTier, str] = {
    KnowledgeTier.T0_PRINCIPLE: "exp_t0_principles",
    KnowledgeTier.T1_BEHAVIORAL: "exp_t1_behavioral",
    KnowledgeTier.T2_QA_CACHE: "exp_t2_qa_cache",
    KnowledgeTier.T3_RAW: "exp_t3_raw",
}

# Always-load tiers searched on every intercept
ALWAYS_LOAD: tuple[KnowledgeTier, ...] = (
    KnowledgeTier.T0_PRINCIPLE,
    KnowledgeTier.T1_BEHAVIORAL,
)
