"""Composite-score ranker for the v2 intercept pipeline.

Implements **Algorithm 5** from the experience-engine-upgrade design document:
the per-candidate scoring function used by ``ExperienceService.intercept_v2``
to order semantic-search hits before the L3 LLM relevance filter.

Composite score (per candidate)::

    score = 0.40 * similarity
          + 0.20 * confidence
          + 0.15 * signal
          + 0.10 * tier_weight
          + 0.10 * recency
          + 0.05 * hits
          - superseded_penalty

Where:

* ``similarity``         — raw cosine score from Qdrant (already in [0, 1]).
* ``confidence``         — stored on the experience, in [0, 1].
* ``signal``             — ``followed / (followed + ignored + 1)`` clamped to
  [0, 1]; rewards experiences the agent has historically followed.
* ``tier_weight``        — T0=1.00, T1=0.85, T2=0.70, T3=0.00; T3 is staging
  and is effectively excluded from suggestions.
* ``recency``            — 1.0 when ``last_used_at`` is within the last
  ``RECENCY_FRESH_DAYS`` (7) days, decays linearly to 0.0 by
  ``RECENCY_STALE_DAYS`` (90) days, then stays at 0.0.
* ``hits``               — ``log10(1 + usage_count) / 3.0`` capped at 1.0;
  saturates at usage_count = 999.
* ``superseded_penalty`` — 1.0 if ``superseded_by`` is not None, else 0.0;
  guarantees superseded experiences cannot win against fresh ones.

Requirements satisfied
----------------------
* **Requirement 1.4** — at most 8 suggestions ordered by descending rank
  score; this module produces the ordering, the caller applies the cap.
* **Requirement 1.7** — suggestions whose ``id`` was already returned in
  the same session MUST be excluded; ``rank()`` skips any candidate whose
  id appears in the ``session_seen`` set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# ── Tier weights ──────────────────────────────────────────────────────────
# T3 is staging only; ranker zeros it out so raw lessons never reach the
# user even if a search accidentally surfaces one.
TIER_WEIGHTS: dict[str, float] = {
    "t0_principle": 1.0,
    "t1_behavioral": 0.85,
    "t2_qa_cache": 0.70,
    "t3_raw": 0.0,
}

# ── Recency window ────────────────────────────────────────────────────────
RECENCY_FRESH_DAYS: int = 7   # full credit within the last week
RECENCY_STALE_DAYS: int = 90  # zero credit at/after 90 days

# ── Composite-score weights (sum = 1.0 before the superseded penalty) ─────
W_SIM: float = 0.40
W_CONF: float = 0.20
W_SIG: float = 0.15
W_TIER: float = 0.10
W_REC: float = 0.10
W_HITS: float = 0.05


@dataclass
class Candidate:
    """A single ranking candidate produced from a Qdrant search hit.

    Attributes
    ----------
    id:
        Experience id (Qdrant point id).
    payload:
        Full Qdrant payload (the serialized ``Experience``).
    score:
        Raw cosine similarity from Qdrant, in [0, 1].
    tier:
        Knowledge tier string (matches keys of :data:`TIER_WEIGHTS`).
    confidence:
        Experience confidence, in [0, 1].
    signal:
        Pre-computed Laplace-style signal in [0, 1] —
        ``followed / (followed + ignored + 1)``.
    last_used_at:
        Timestamp of the most recent intercept that surfaced this
        experience; ``None`` if never used.
    usage_count:
        Total number of intercepts that have surfaced this experience.
    superseded_by:
        Id of the experience that supersedes this one, or ``None``.
    composite_score:
        Filled in by :func:`rank`; the final ordered score used for
        sorting and budget-cap selection.
    """

    id: str
    payload: dict[str, Any]
    score: float
    tier: str
    confidence: float
    signal: float
    last_used_at: Optional[datetime]
    usage_count: int
    superseded_by: Optional[str]
    composite_score: float = field(default=0.0)


def _clamp01(value: float) -> float:
    """Clamp ``value`` into the closed unit interval [0, 1]."""
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def _recency_score(last_used_at: Optional[datetime], *, now: datetime) -> float:
    """Compute the recency component.

    Returns 1.0 if ``last_used_at`` is within ``RECENCY_FRESH_DAYS`` of
    ``now``, then decays linearly to 0.0 by ``RECENCY_STALE_DAYS``, and
    stays at 0.0 thereafter. Returns 0.0 when ``last_used_at`` is ``None``.
    """
    if last_used_at is None:
        return 0.0

    # Normalize to timezone-aware UTC for a safe subtraction.
    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)

    days = (now - last_used_at).total_seconds() / 86_400.0
    if days <= RECENCY_FRESH_DAYS:
        return 1.0
    if days >= RECENCY_STALE_DAYS:
        return 0.0
    # Linear decay between the two thresholds.
    span = float(RECENCY_STALE_DAYS - RECENCY_FRESH_DAYS)
    return 1.0 - (days - RECENCY_FRESH_DAYS) / span


def _hits_score(usage_count: int) -> float:
    """Compute the hits component: ``log10(1 + usage_count) / 3`` capped at 1.0."""
    if usage_count <= 0:
        return 0.0
    return _clamp01(math.log10(1 + usage_count) / 3.0)


def _composite(candidate: Candidate, *, now: datetime) -> float:
    """Compute the composite score for a single candidate.

    Algorithm 5 — see module docstring for the breakdown.
    """
    similarity = _clamp01(candidate.score)
    confidence = _clamp01(candidate.confidence)
    signal = _clamp01(candidate.signal)
    tier_weight = TIER_WEIGHTS.get(candidate.tier, 0.0)
    recency = _recency_score(candidate.last_used_at, now=now)
    hits = _hits_score(candidate.usage_count)
    superseded_penalty = 1.0 if candidate.superseded_by is not None else 0.0

    return (
        W_SIM * similarity
        + W_CONF * confidence
        + W_SIG * signal
        + W_TIER * tier_weight
        + W_REC * recency
        + W_HITS * hits
        - superseded_penalty
    )


def rank(
    candidates: list[Candidate],
    *,
    session_seen: Optional[set[str]] = None,
) -> list[Candidate]:
    """Rank ``candidates`` by composite score and apply session deduplication.

    Implements Algorithm 5 of the experience-engine-upgrade design document
    and supports Requirement 1.7 by excluding any candidate whose ``id`` is
    already present in ``session_seen``.

    Parameters
    ----------
    candidates:
        Raw candidates pulled from one or more tier searches. The list is
        not mutated; ranked copies (with ``composite_score`` populated) are
        returned.
    session_seen:
        Set of experience ids that have already been surfaced in earlier
        intercepts of the current session. Candidates whose id appears in
        this set are excluded from the result. ``None`` means "no session
        dedup".

    Returns
    -------
    list[Candidate]
        The retained candidates, each with its ``composite_score`` field
        populated, sorted in descending order of ``composite_score``.

    Notes
    -----
    Sorting is stable: candidates with identical composite scores keep the
    relative order in which Qdrant returned them, which respects raw
    similarity as a natural tiebreaker.
    """
    seen = session_seen or set()
    now = datetime.now(timezone.utc)

    ranked: list[Candidate] = []
    for c in candidates:
        if c.id in seen:
            # Requirement 1.7 — session deduplication.
            continue
        c.composite_score = _composite(c, now=now)
        ranked.append(c)

    ranked.sort(key=lambda x: x.composite_score, reverse=True)
    return ranked


def build_candidate_from_hit(hit: dict[str, Any]) -> Candidate:
    """Convert a Qdrant search hit into a :class:`Candidate`.

    Expected hit shape::

        {
            "id":      "<experience id>",
            "payload": { ...full Experience JSON... },
            "score":   0.87,                 # cosine similarity
            "tier":    "t1_behavioral",      # KnowledgeTier value
        }

    The payload provides the v2 fields (``confidence``, ``followed_count``,
    ``ignored_count``, ``last_used_at``, ``usage_count``, ``superseded_by``)
    that feed the composite score.

    Robustness
    ----------
    * Missing optional fields default to neutral values (0 / None / 0.5)
      so a v1 payload that lacks evolution metadata still ranks sensibly.
    * ``last_used_at`` is parsed from ISO-8601 strings if present.
    * ``signal`` is computed as ``followed / (followed + ignored + 1)`` and
      clamped to [0, 1] — using ``+ 1`` (not ``+ 2``) per Requirement 1.4.
    """
    payload: dict[str, Any] = hit.get("payload") or {}

    # Tier may live at the top level (preferred) or inside the payload.
    tier = hit.get("tier") or payload.get("tier") or "t2_qa_cache"

    confidence = float(payload.get("confidence", 0.5))
    followed = int(payload.get("followed_count", 0))
    ignored = int(payload.get("ignored_count", 0))
    usage_count = int(payload.get("usage_count", 0))
    superseded_by = payload.get("superseded_by")

    # signal = followed / (followed + ignored + 1), clamped to [0, 1].
    denom = followed + ignored + 1
    signal_raw = followed / denom if denom > 0 else 0.0
    signal = _clamp01(signal_raw)

    last_used_at_raw = payload.get("last_used_at")
    last_used_at: Optional[datetime] = None
    if isinstance(last_used_at_raw, datetime):
        last_used_at = last_used_at_raw
    elif isinstance(last_used_at_raw, str) and last_used_at_raw:
        try:
            # ``fromisoformat`` handles ``+00:00`` directly; normalize ``Z``.
            last_used_at = datetime.fromisoformat(last_used_at_raw.replace("Z", "+00:00"))
        except ValueError:
            last_used_at = None

    hit_id = hit.get("id")
    if hit_id is None:
        hit_id = payload.get("id")

    return Candidate(
        id=str(hit_id) if hit_id is not None else "None",
        payload=payload,
        score=float(hit.get("score", 0.0)),
        tier=str(tier),
        confidence=confidence,
        signal=signal,
        last_used_at=last_used_at,
        usage_count=usage_count,
        superseded_by=superseded_by if superseded_by else None,
    )
