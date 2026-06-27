"""
PIL (Prompt Intent Layer) Enricher — 6-layer pipeline for intercept preprocessing.

Enriches an InterceptRequest with intent classification, tag extraction, and
contextual information before semantic search. Operates under a hard 200ms budget
using asyncio.wait_for. Fail-open at every layer: if any step throws or the
overall budget is exceeded, returns the original action with confidence=0.0.

Layers:
  1. intent_detection     — classify action into plan|generate|refactor|debug|docs|analyze
  2. tag_extraction       — extract language, framework, file patterns from action text
  3. ee_pattern_lookup    — match against known experience engine patterns
  4. workflow_classification — determine workflow context (single, multi-step, etc.)
  5. context_injection    — inject file_path, language, and agent context
  6. output_shaping       — compose final enriched string for embedding

Requirements: 1.2, 1.3
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from src.domain.models import InterceptRequest

logger = logging.getLogger(__name__)


# ==================== Constants ====================

# Hard budget for the entire enrichment pipeline (milliseconds)
PIL_BUDGET_MS: float = 200.0

# Intent keywords mapped to intent categories
INTENT_KEYWORDS: dict[str, list[str]] = {
    "plan": [
        "plan", "design", "architect", "outline", "structure", "organize",
        "propose", "strategy", "roadmap", "scaffold",
    ],
    "generate": [
        "create", "generate", "write", "add", "implement", "build", "make",
        "new", "scaffold", "init", "setup", "bootstrap",
    ],
    "refactor": [
        "refactor", "rename", "move", "extract", "inline", "simplify",
        "clean", "reorganize", "restructure", "optimize", "improve",
    ],
    "debug": [
        "debug", "fix", "resolve", "troubleshoot", "investigate", "diagnose",
        "error", "bug", "issue", "crash", "fail", "broken",
    ],
    "docs": [
        "document", "docs", "comment", "readme", "explain", "describe",
        "annotate", "jsdoc", "docstring", "changelog",
    ],
    "analyze": [
        "analyze", "review", "audit", "inspect", "check", "assess",
        "evaluate", "examine", "profile", "benchmark", "test",
    ],
}

# Known language indicators (file extensions and keywords)
LANGUAGE_INDICATORS: dict[str, list[str]] = {
    "typescript": ["typescript", ".ts", ".tsx", "ts", "tsx", "angular", "nest"],
    "javascript": ["javascript", ".js", ".jsx", "js", "jsx", "node", "express", "react", "vue"],
    "python": ["python", ".py", "py", "django", "flask", "fastapi", "pytest"],
    "rust": ["rust", ".rs", "rs", "cargo", "tokio"],
    "go": ["golang", ".go", "go", "gin", "fiber"],
    "java": ["java", ".java", "spring", "maven", "gradle"],
    "csharp": ["csharp", "c#", ".cs", "cs", "dotnet", ".net", "aspnet"],
    "ruby": ["ruby", ".rb", "rb", "rails", "sinatra"],
    "sql": ["sql", ".sql", "postgres", "mysql", "sqlite", "query", "migration"],
    "html": ["html", ".html", "htm", "template"],
    "css": ["css", ".css", "scss", "sass", "tailwind", "styled"],
}

# Known framework indicators
FRAMEWORK_INDICATORS: dict[str, list[str]] = {
    "react": ["react", "jsx", "tsx", "component", "hook", "useState", "useEffect"],
    "vue": ["vue", "vuex", "pinia", "nuxt"],
    "angular": ["angular", "ng", "rxjs", "observable"],
    "fastapi": ["fastapi", "uvicorn", "pydantic"],
    "django": ["django", "drf", "serializer"],
    "express": ["express", "middleware", "router"],
    "nextjs": ["next", "nextjs", "getServerSideProps", "getStaticProps"],
    "spring": ["spring", "springboot", "bean", "autowired"],
}

# File pattern regex for extraction
FILE_PATTERN_RE = re.compile(
    r"""
    (?:^|\s|['"`])                  # start or whitespace or quote
    (
        [\w./\\-]+                  # path characters
        \.                          # dot before extension
        [a-zA-Z]{1,6}              # extension (1-6 chars)
    )
    (?:\s|['"`]|$)                  # end or whitespace or quote
    """,
    re.VERBOSE,
)

# Glob-like patterns
GLOB_PATTERN_RE = re.compile(r"[\w./\\-]*\*[\w./\\*-]*")


# ==================== Models ====================


class EnrichedPrompt(BaseModel):
    """Result of PIL enrichment pipeline.

    Contains the original action, the enriched string for embedding,
    detected intent, extracted tags, optional file pattern, and
    confidence score indicating enrichment quality.
    """

    original: str = Field(..., description="Original action text from the request")
    enriched: str = Field(..., description="Final enriched string to embed for semantic search")
    intent: str = Field(
        default="generate",
        description="Detected intent: plan | generate | refactor | debug | docs | analyze",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Auto-extracted tags (language, framework, file glob)",
    )
    file_pattern: Optional[str] = Field(
        default=None,
        description="Detected file pattern or glob from the action text",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Enrichment confidence 0.0–1.0; 0.0 means fallback/unenriched",
    )


# ==================== PILEnricher ====================


class PILEnricher:
    """6-layer Prompt Intent Layer pipeline.

    Hard budget: 200ms total via asyncio.wait_for.
    Fail-open: on timeout or any error, returns original action with confidence=0.0.

    Layers executed in sequence:
      1. intent_detection
      2. tag_extraction
      3. ee_pattern_lookup
      4. workflow_classification
      5. context_injection
      6. output_shaping
    """

    async def enrich(self, req: InterceptRequest) -> EnrichedPrompt:
        """Run the 6-layer enrichment pipeline within a 200ms hard budget.

        Args:
            req: The intercept request to enrich.

        Returns:
            EnrichedPrompt with intent, tags, and enriched text.
            On timeout or error, returns original action with confidence=0.0.
        """
        try:
            result = await asyncio.wait_for(
                self._run_pipeline(req),
                timeout=PIL_BUDGET_MS / 1000.0,  # convert ms to seconds
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "PIL enrichment exceeded %dms budget, returning original action",
                int(PIL_BUDGET_MS),
            )
            return self._fail_open(req)
        except Exception:
            logger.exception("PIL enrichment failed, returning original action")
            return self._fail_open(req)

    async def _run_pipeline(self, req: InterceptRequest) -> EnrichedPrompt:
        """Execute all 6 layers sequentially, fail-open at each layer."""
        action = req.action
        intent = "generate"
        tags: list[str] = []
        file_pattern: Optional[str] = None
        confidence = 0.0
        workflow_hint = ""
        context_parts: list[str] = []

        # Layer 1: Intent Detection
        try:
            intent, intent_conf = self._detect_intent(action)
            confidence += intent_conf * 0.3  # intent contributes 30% to confidence
        except Exception:
            logger.debug("PIL layer 1 (intent_detection) failed, skipping")

        # Layer 2: Tag Extraction
        try:
            tags, file_pattern = self._extract_tags(action, req)
            if tags:
                confidence += 0.25  # tags contribute 25% to confidence
        except Exception:
            logger.debug("PIL layer 2 (tag_extraction) failed, skipping")

        # Layer 3: EE Pattern Lookup
        try:
            pattern_boost = self._ee_pattern_lookup(action, intent, tags)
            confidence += pattern_boost * 0.15  # pattern match contributes 15%
        except Exception:
            logger.debug("PIL layer 3 (ee_pattern_lookup) failed, skipping")

        # Layer 4: Workflow Classification
        try:
            workflow_hint = self._classify_workflow(action, intent)
            if workflow_hint:
                confidence += 0.1  # workflow contributes 10%
        except Exception:
            logger.debug("PIL layer 4 (workflow_classification) failed, skipping")

        # Layer 5: Context Injection
        try:
            context_parts = self._inject_context(req)
            if context_parts:
                confidence += 0.1  # context contributes 10%
        except Exception:
            logger.debug("PIL layer 5 (context_injection) failed, skipping")

        # Layer 6: Output Shaping
        try:
            enriched = self._shape_output(
                action=action,
                intent=intent,
                tags=tags,
                file_pattern=file_pattern,
                workflow_hint=workflow_hint,
                context_parts=context_parts,
            )
            if enriched != action:
                confidence += 0.1  # shaping contributes 10%
        except Exception:
            logger.debug("PIL layer 6 (output_shaping) failed, using original action")
            enriched = action

        # Clamp confidence to [0.0, 1.0]
        confidence = min(max(confidence, 0.0), 1.0)

        return EnrichedPrompt(
            original=action,
            enriched=enriched,
            intent=intent,
            tags=tags,
            file_pattern=file_pattern,
            confidence=confidence,
        )

    # ==================== Layer Implementations ====================

    def _detect_intent(self, action: str) -> tuple[str, float]:
        """Layer 1: Classify action into one of 6 intent categories.

        Returns (intent, confidence) where confidence is 0.0–1.0.
        Uses keyword frequency matching against known intent patterns.
        """
        action_lower = action.lower()
        words = set(re.findall(r"\b\w+\b", action_lower))

        scores: dict[str, float] = {}
        for intent_name, keywords in INTENT_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in words or kw in action_lower)
            if matches > 0:
                scores[intent_name] = matches / len(keywords)

        if not scores:
            return "generate", 0.3  # default intent with low confidence

        best_intent = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best_intent]

        # Normalize confidence: more keyword matches = higher confidence
        confidence = min(best_score * 3.0, 1.0)  # scale up, cap at 1.0
        return best_intent, confidence

    def _extract_tags(
        self, action: str, req: InterceptRequest
    ) -> tuple[list[str], Optional[str]]:
        """Layer 2: Extract language, framework, and file pattern tags.

        Combines action text analysis with request metadata (language, file_path).
        Returns (tags, file_pattern).
        """
        tags: list[str] = []
        action_lower = action.lower()

        # Extract language from action text
        for lang, indicators in LANGUAGE_INDICATORS.items():
            if any(ind in action_lower for ind in indicators):
                if lang not in tags:
                    tags.append(lang)
                break  # take first match

        # Use request metadata language if available and not already detected
        if req.language and req.language.lower() not in tags:
            tags.append(req.language.lower())

        # Extract framework
        for framework, indicators in FRAMEWORK_INDICATORS.items():
            if any(ind in action_lower for ind in indicators):
                if framework not in tags:
                    tags.append(framework)
                break  # take first match

        # Extract file patterns
        file_pattern: Optional[str] = None

        # Check for glob patterns first
        glob_matches = GLOB_PATTERN_RE.findall(action)
        if glob_matches:
            file_pattern = glob_matches[0]
            tags.append(f"glob:{file_pattern}")

        # Check for specific file paths
        if not file_pattern:
            file_matches = FILE_PATTERN_RE.findall(action)
            if file_matches:
                file_pattern = file_matches[0]

        # Use request file_path as fallback
        if not file_pattern and req.file_path:
            file_pattern = req.file_path

        return tags, file_pattern

    def _ee_pattern_lookup(
        self, action: str, intent: str, tags: list[str]
    ) -> float:
        """Layer 3: Look up known experience engine patterns.

        Checks if the action+intent+tags combination matches patterns that
        historically produce high-quality enrichment. Returns a boost factor 0.0–1.0.
        """
        boost = 0.0
        action_lower = action.lower()

        # Pattern: specific file operation with known language → high relevance
        if tags and intent in ("generate", "refactor", "debug"):
            boost += 0.5

        # Pattern: action mentions specific error/exception → debug context rich
        error_indicators = ["error", "exception", "traceback", "stack", "panic", "segfault"]
        if any(ind in action_lower for ind in error_indicators):
            boost += 0.3

        # Pattern: action mentions test → likely has clear success criteria
        test_indicators = ["test", "spec", "assert", "expect", "should"]
        if any(ind in action_lower for ind in test_indicators):
            boost += 0.2

        return min(boost, 1.0)

    def _classify_workflow(self, action: str, intent: str) -> str:
        """Layer 4: Determine workflow classification.

        Returns a workflow hint string that helps contextualize the action
        for better embedding similarity.
        """
        action_lower = action.lower()

        # Multi-step indicators
        multi_step_indicators = [
            "then", "after", "before", "first", "next", "finally",
            "step", "phase", "migrate", "convert",
        ]
        if any(ind in action_lower for ind in multi_step_indicators):
            return "multi-step"

        # Research/exploration indicators
        research_indicators = [
            "compare", "evaluate", "which", "should", "best", "alternative",
            "option", "trade-off", "tradeoff", "pros", "cons",
        ]
        if any(ind in action_lower for ind in research_indicators):
            return "research"

        # Quick-fix indicators
        quick_indicators = ["quick", "simple", "just", "only", "small", "minor", "typo"]
        if any(ind in action_lower for ind in quick_indicators):
            return "quick-fix"

        # Map intent to default workflow
        intent_workflow_map = {
            "plan": "planning",
            "generate": "implementation",
            "refactor": "transformation",
            "debug": "investigation",
            "docs": "documentation",
            "analyze": "analysis",
        }
        return intent_workflow_map.get(intent, "implementation")

    def _inject_context(self, req: InterceptRequest) -> list[str]:
        """Layer 5: Inject contextual information from the request.

        Gathers file_path, language, agent, and any additional context
        from the request to enrich the final output.
        """
        parts: list[str] = []

        if req.language:
            parts.append(f"lang:{req.language}")

        if req.file_path:
            parts.append(f"file:{req.file_path}")

        if req.agent:
            parts.append(f"agent:{req.agent}")

        if req.context:
            # Truncate context to avoid bloating the enriched string
            ctx = req.context[:200] if len(req.context) > 200 else req.context
            parts.append(f"ctx:{ctx}")

        return parts

    def _shape_output(
        self,
        action: str,
        intent: str,
        tags: list[str],
        file_pattern: Optional[str],
        workflow_hint: str,
        context_parts: list[str],
    ) -> str:
        """Layer 6: Compose the final enriched string for embedding.

        Combines all extracted information into a structured string that
        maximizes semantic search relevance.
        """
        parts: list[str] = []

        # Intent prefix for embedding alignment
        parts.append(f"[{intent}]")

        # Tags as compact prefix
        if tags:
            parts.append(f"({', '.join(tags)})")

        # Original action is always the core
        parts.append(action)

        # File pattern suffix
        if file_pattern:
            parts.append(f"@ {file_pattern}")

        # Workflow hint
        if workflow_hint:
            parts.append(f"| {workflow_hint}")

        # Context injection (compact)
        if context_parts:
            parts.append(f"[{' '.join(context_parts)}]")

        return " ".join(parts)

    # ==================== Helpers ====================

    def _fail_open(self, req: InterceptRequest) -> EnrichedPrompt:
        """Return a safe fallback EnrichedPrompt with confidence=0.0.

        Used when the pipeline times out or encounters an unrecoverable error.
        The original action is used as-is for embedding.
        """
        return EnrichedPrompt(
            original=req.action,
            enriched=req.action,
            intent="generate",
            tags=[],
            file_pattern=None,
            confidence=0.0,
        )
