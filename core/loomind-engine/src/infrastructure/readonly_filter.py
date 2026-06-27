"""
Hardened read-only command filter using token-based matching.

Replaces naive `includes()` approach that caused false positives
(e.g., "delete the cat folder" matching "cat"). This implementation
tokenizes the action and checks only the FIRST token(s) of each
chained-command segment against known read-only command sets.

Algorithm 7 from the design document.
"""

from __future__ import annotations

import re

# ─── Read-only command sets ────────────────────────────────────────────────────

READONLY_SINGLE_TOKEN: frozenset[str] = frozenset({
    "ls", "cat", "head", "tail", "grep", "find", "echo", "pwd",
    "whoami", "date", "which", "where", "type", "file", "wc", "diff",
    "less", "more", "man", "help", "env", "printenv", "hostname",
    "uname", "id", "df", "du", "free", "uptime", "ps", "top",
    "htop", "tree", "stat", "readlink", "realpath", "basename",
    "dirname", "sha256sum", "md5sum", "xxd", "hexdump", "strings",
    "nm", "ldd", "objdump",
    # Network inspection (read-only for simplicity)
    "curl", "wget", "ping", "traceroute", "dig", "nslookup",
    # Agent/Tool read-only commands
    "view_file", "list_dir", "grep_search", "read_file", "search_web",
})

READONLY_TWO_TOKEN: frozenset[str] = frozenset({
    "git log", "git status", "git diff", "git show",
    "git branch", "git remote", "git tag",
    "docker ps", "docker images", "docker inspect", "docker logs",
    "npm list", "npm info",
    "pip list", "pip show",
})

# ─── Chained-command separators ────────────────────────────────────────────────

# Split on ;  &&  ||  | (but not || which is already covered — we split greedily)
# Order matters: match "||" and "&&" before single "|"
_CHAIN_SPLIT_RE = re.compile(r"\s*(?:;|&&|\|\||\|)\s*")


def _strip_run_prefix(segment: str) -> str:
    """Strip a leading 'run ' prefix if present (common in agent actions)."""
    if segment.startswith("run "):
        return segment[4:]
    return segment


def _starts_with_readonly_token(segment: str) -> bool:
    """Check if a single command segment starts with a recognized read-only token.

    Tokenizes on whitespace and checks:
    1. First token against READONLY_SINGLE_TOKEN
    2. First two tokens (joined) against READONLY_TWO_TOKEN
    """
    stripped = _strip_run_prefix(segment.strip())
    parts = stripped.split()

    if not parts:
        return False

    head = parts[0]

    # Check single-token read-only commands
    if head in READONLY_SINGLE_TOKEN:
        return True

    # Check two-token read-only commands (e.g., "git log", "docker ps")
    if len(parts) >= 2:
        two_token = head + " " + parts[1]
        if two_token in READONLY_TWO_TOKEN:
            return True

    return False


def is_readonly(action: str) -> bool:
    """Determine if an action is read-only using token-based matching.

    Handles chained commands separated by ;, &&, ||, or |.
    ALL segments must start with a recognized read-only command token
    for the entire action to be classified as read-only.

    If ANY segment is NOT read-only, the action is considered mutating.

    Args:
        action: The action string to classify.

    Returns:
        True if the action is read-only, False if it is mutating.
    """
    if not action or not action.strip():
        return False

    lowered = action.lower()

    # Split on chained-command separators
    segments = _CHAIN_SPLIT_RE.split(lowered)

    # ALL segments must be read-only for the whole action to be read-only
    for segment in segments:
        segment = segment.strip()
        if not segment:
            # Empty segments (e.g., trailing separator) — skip
            continue
        if not _starts_with_readonly_token(segment):
            return False

    return True
