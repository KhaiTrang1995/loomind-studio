"""Ranking domain package.

Exposes the composite-score ranker used inside the v2 intercept pipeline
(see Algorithm 5 in the experience-engine-upgrade design document).
"""

from src.domain.ranking.ranker import (
    RECENCY_FRESH_DAYS,
    RECENCY_STALE_DAYS,
    TIER_WEIGHTS,
    W_CONF,
    W_HITS,
    W_REC,
    W_SIG,
    W_SIM,
    W_TIER,
    Candidate,
    build_candidate_from_hit,
    rank,
)

__all__ = [
    "Candidate",
    "rank",
    "build_candidate_from_hit",
    "TIER_WEIGHTS",
    "RECENCY_FRESH_DAYS",
    "RECENCY_STALE_DAYS",
    "W_SIM",
    "W_CONF",
    "W_SIG",
    "W_TIER",
    "W_REC",
    "W_HITS",
]
