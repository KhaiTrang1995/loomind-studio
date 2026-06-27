"""
Deliberation Service — multi-CLI consensus engine.

When a CLI hits a problem it can't resolve alone, it POST /api/deliberate.
The engine picks consultant CLIs, spawns them headless with a structured
prompt, collects their votes, and resolves consensus — or escalates to HITL.

Consensus rules:
  - All consultants vote "agree"            → resolved immediately
  - ≥60% agree + avg confidence ≥ 0.7      → resolved
  - Any vote "need_human"                   → HITL (security guard)
  - Topic contains security keywords        → HITL, no deliberation
  - max_rounds exceeded without consensus   → HITL

Security constraint: SECURITY topics NEVER auto-resolve regardless of votes.

Phase 12 — Multi-CLI Deliberation.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.infrastructure.cli_executor import CLIExecutor
    from src.infrastructure.cli_registry import CLIRegistry
    from src.infrastructure.event_bus import EventBus

from src.domain.models import (
    CLIStatus,
    ConsultRequest,
    ConsultResponse,
    Deliberation,
    DeliberationRound,
    DeliberationStatus,
    DeliberationVote,
    HITLResolveRequest,
)

logger = logging.getLogger(__name__)

# These topics bypass deliberation and go straight to HITL
_SECURITY_KEYWORDS = frozenset({
    "delete", "drop", "truncate", "rm -rf", "format",
    "security", "auth", "credential", "password", "secret", "token",
    "prod", "production", "deploy", "rollback", "migration",
})


class DeliberationService:
    def __init__(
        self,
        executor: "CLIExecutor",
        cli_registry: "CLIRegistry",
        event_bus: "EventBus",
        max_rounds: int = 3,
        cli_timeout: int = 300,
        experience_service: object = None,
    ) -> None:
        self._executor = executor
        self._cli_registry = cli_registry
        self._bus = event_bus
        self._max_rounds = max_rounds
        self._cli_timeout = cli_timeout
        self._experience_service = experience_service
        self._deliberations: dict[str, Deliberation] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def get_all(self) -> list[Deliberation]:
        return sorted(self._deliberations.values(), key=lambda d: d.created_at, reverse=True)

    def get(self, deliberation_id: str) -> Optional[Deliberation]:
        return self._deliberations.get(deliberation_id)

    async def start(self, request: ConsultRequest) -> ConsultResponse:
        """Create a deliberation and kick off async rounds. Returns immediately."""
        is_security = self._is_security_topic(request.topic + " " + request.context)

        participants = self._cli_registry.pick_consultants(
            initiator=request.from_cli,
            preferred=request.preferred_consultants or None,
        )

        d = Deliberation(
            topic=request.topic,
            context=request.context,
            initiator=request.from_cli,
            participants=participants,
            max_rounds=self._max_rounds,
            status=DeliberationStatus.HITL_PENDING if is_security else DeliberationStatus.OPEN,
        )
        self._deliberations[d.deliberation_id] = d

        if is_security:
            logger.warning(
                "Deliberation %s flagged SECURITY — forced HITL, no auto-resolve",
                d.deliberation_id,
            )
            self._broadcast(d)
        else:
            asyncio.create_task(self._run_rounds(d))

        return ConsultResponse(
            deliberation_id=d.deliberation_id,
            status=d.status,
            consensus=d.consensus,
            rounds_so_far=len(d.rounds),
        )

    async def resolve_hitl(self, deliberation_id: str, body: HITLResolveRequest) -> Optional[Deliberation]:
        """Human manually resolves a HITL-pending deliberation."""
        d = self._deliberations.get(deliberation_id)
        if d is None:
            return None

        d.status = DeliberationStatus.RESOLVED if body.approved else DeliberationStatus.CANCELLED
        d.consensus = body.consensus if body.approved else None
        d.resolved_at = datetime.now(timezone.utc)
        self._broadcast(d)

        if body.approved and d.consensus:
            self._bus.publish(d.initiator, {
                "event": "deliberation_resolved",
                "payload": {
                    "deliberation_id": d.deliberation_id,
                    "consensus": d.consensus,
                    "human_approved": True,
                },
            })
            asyncio.create_task(self._auto_save_experience(d, human_approved=True))
        return d

    # ── Round execution ───────────────────────────────────────────────────────

    async def _run_rounds(self, d: Deliberation) -> None:
        for round_num in range(1, d.max_rounds + 1):
            if d.status != DeliberationStatus.OPEN:
                break

            available = [c for c in d.participants if self._executor.is_available(c)]
            if not available:
                logger.warning("Deliberation %s: no available consultants, escalating to HITL", d.deliberation_id)
                d.status = DeliberationStatus.HITL_PENDING
                self._broadcast(d)
                return

            prompt = self._build_prompt(d, round_num)
            logger.info("Deliberation %s round %d/%d — consulting %s", d.deliberation_id, round_num, d.max_rounds, available)

            await asyncio.gather(*[self._consult_one(d, cli, prompt) for cli in available])
            self._broadcast(d)

            if self._check_consensus(d):
                return

        # Exhausted rounds without consensus
        if d.status == DeliberationStatus.OPEN:
            d.status = DeliberationStatus.HITL_PENDING
            logger.warning("Deliberation %s → HITL after %d rounds", d.deliberation_id, d.max_rounds)
            self._broadcast(d)

    async def _consult_one(self, d: Deliberation, cli: str, prompt: str) -> None:
        self._cli_registry.set_busy(cli, task=d.topic[:80], deliberation_id=d.deliberation_id)
        try:
            result = await self._executor.run(
                cli=cli,
                prompt=prompt,
                deliberation_id=d.deliberation_id,
                timeout=self._cli_timeout,
            )
            vote_val = result.vote if result.vote in DeliberationVote._value2member_map_ else "abstain"
            d.rounds.append(DeliberationRound(
                agent=cli,
                proposal=result.recommendation or result.output[:2000],
                vote=DeliberationVote(vote_val),
                confidence=result.confidence,
            ))
        except Exception:
            logger.exception("Consultation error for %s in deliberation %s", cli, d.deliberation_id)
            d.rounds.append(DeliberationRound(
                agent=cli,
                proposal="[error during consultation]",
                vote=DeliberationVote.ABSTAIN,
                confidence=0.0,
            ))
        finally:
            self._cli_registry.set_idle(cli)

    def _check_consensus(self, d: Deliberation) -> bool:
        """Evaluate latest round votes. Mutates d.status on resolution."""
        if not d.rounds:
            return False

        # Latest round = last N rounds where N = len(participants)
        latest = d.rounds[-len(d.participants):]

        # Any NEED_HUMAN → immediate HITL
        if any(r.vote == DeliberationVote.NEED_HUMAN for r in latest):
            d.status = DeliberationStatus.HITL_PENDING
            logger.warning("Deliberation %s → HITL (NEED_HUMAN vote)", d.deliberation_id)
            return True

        agree_count = sum(1 for r in latest if r.vote == DeliberationVote.AGREE)
        total = len(latest)
        avg_conf = sum(r.confidence for r in latest) / total if total else 0.0

        if agree_count == total or (agree_count / total >= 0.6 and avg_conf >= 0.7):
            d.status = DeliberationStatus.RESOLVED
            d.consensus = self._best_proposal(latest)
            d.resolved_at = datetime.now(timezone.utc)
            logger.info("Deliberation %s resolved (agree=%d/%d conf=%.2f)", d.deliberation_id, agree_count, total, avg_conf)
            self._broadcast(d)
            self._bus.publish(d.initiator, {
                "event": "deliberation_resolved",
                "payload": {
                    "deliberation_id": d.deliberation_id,
                    "consensus": d.consensus,
                    "rounds": len(d.rounds),
                },
            })
            asyncio.create_task(self._auto_save_experience(d))
            return True
        return False

    # ── Experience auto-save ──────────────────────────────────────────────────

    async def _auto_save_experience(self, d: Deliberation, human_approved: bool = False) -> None:
        """Save resolved deliberation consensus as a Loomind experience."""
        if self._experience_service is None or not d.consensus:
            return
        try:
            from src.domain.models import CreateExperienceRequest
            import asyncio as _asyncio
            source = "human-approved deliberation" if human_approved else "multi-cli consensus"
            description = (
                f"[{source}] {d.topic}\n\n"
                f"Consensus:\n{d.consensus}\n\n"
                f"Participants: {', '.join(d.participants)} | Rounds: {len(d.rounds)}"
            )
            req = CreateExperienceRequest(
                title=f"[Deliberation] {d.topic[:80]}",
                description=description,
                category="deliberation",
                tags=list({"deliberation", "multi-cli", d.initiator, *d.participants}),
            )
            await _asyncio.get_event_loop().run_in_executor(
                None, self._experience_service.create_experience, req
            )
            logger.info("Auto-saved experience for deliberation %s", d.deliberation_id)
        except Exception:
            logger.exception("Failed to auto-save experience for deliberation %s", d.deliberation_id)

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_prompt(self, d: Deliberation, round_num: int) -> str:
        prev = ""
        if d.rounds:
            lines = [
                f"  - {r.agent}: {r.proposal[:200]} [vote={r.vote.value}, conf={r.confidence:.1f}]"
                for r in d.rounds[-len(d.participants):]
            ]
            prev = "\nPrevious round:\n" + "\n".join(lines)

        return f"""You are a senior AI agent in a multi-agent deliberation system.
Your goal is to reach a concrete, actionable consensus — not to equivocate.

DELIBERATION TOPIC:
{d.topic}

CONTEXT:
{d.context or "(no additional context provided)"}
{prev}

ROUND {round_num}/{d.max_rounds}

Provide your analysis:
1. Your recommendation (2-3 sentences, be specific)
2. Reasoning (max 3 bullet points)
3. Any concerns or trade-offs

End your response with EXACTLY this JSON line (no trailing text after it):
{{"vote": "<vote>", "confidence": <0.0-1.0>, "recommendation": "<one-line summary>"}}

Where <vote> must be one of:
  "agree"           — you support the current best proposal fully
  "disagree"        — you oppose the current direction, see your counter above
  "counter_propose" — you have a better solution (describe it above)
  "need_human"      — this involves security/credentials/prod/irreversible actions

Be decisive. "It depends" is not an acceptable answer without a concrete recommendation."""

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_security_topic(text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in _SECURITY_KEYWORDS)

    @staticmethod
    def _best_proposal(rounds: list[DeliberationRound]) -> str:
        best = max(rounds, key=lambda r: r.confidence)
        return best.proposal

    def _broadcast(self, d: Deliberation) -> None:
        self._bus.broadcast({
            "event": "deliberation_update",
            "payload": {
                "deliberation_id": d.deliberation_id,
                "status": d.status.value,
                "topic": d.topic[:80],
                "initiator": d.initiator,
                "participants": d.participants,
                "rounds": len(d.rounds),
                "consensus": d.consensus,
            },
        })
