"""
domain/pil — Prompt Intent Layer (PIL) enrichment pipeline.

Provides a 6-layer in-band enricher with a 200ms hard budget that augments
intercept requests with intent, tags, and contextual information before
semantic search. Fail-open at every step so PIL never blocks the pipeline.
"""

from src.domain.pil.pil_enricher import EnrichedPrompt, PILEnricher

__all__ = ["EnrichedPrompt", "PILEnricher"]
