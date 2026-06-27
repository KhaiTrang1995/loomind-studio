"""
Secret redaction utility — replaces sensitive patterns before embedder/LLM calls.

Patterns: sk-*, ghp_*, AKIA*, xox*, Bearer tokens >20 chars,
*_KEY/*_SECRET/*_TOKEN variable assignments.

Requirements: 11.1, 11.4
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# Compiled regex patterns for secret detection
_PATTERNS: list[re.Pattern[str]] = [
    # API keys with known prefixes
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{12,}\b"),
    re.compile(r"\bxox[bpsar]-[A-Za-z0-9-]{10,}\b"),
    # Bearer tokens longer than 20 chars
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{21,}\b"),
    # Variable assignments like API_KEY="...", DB_SECRET=..., AUTH_TOKEN='...'
    re.compile(r"(?i)\b\w+(?:_KEY|_SECRET|_TOKEN)\s*[=:]\s*['\"]?[A-Za-z0-9._~+/=-]{8,}['\"]?"),
    # Generic long hex/base64 strings that look like secrets (40+ chars)
    re.compile(r"(?<![A-Za-z0-9])[A-Fa-f0-9]{40,}(?![A-Za-z0-9])"),
]

REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Replace detected secret patterns with [REDACTED].

    Args:
        text: Input text that may contain secrets.

    Returns:
        Text with all detected secrets replaced.

    Raises:
        RedactionError: If redaction itself fails (never pass unredacted text).
    """
    if not text:
        return text

    try:
        result = text
        for pattern in _PATTERNS:
            result = pattern.sub(REDACTED, result)
        return result
    except Exception as exc:
        raise RedactionError(f"Redaction failed: {exc}") from exc


class RedactionError(Exception):
    """Raised when redaction itself fails — must reject the request."""
    pass
