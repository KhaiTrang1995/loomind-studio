#!/usr/bin/env python3
"""pre-commit hook — dependency-free secret scanner for staged files.

Why not gitleaks? The gitleaks pre-commit hook builds from source via the Go
toolchain, which isn't guaranteed on every contributor / CI / agent machine.
This scanner needs nothing but a Python interpreter, so the "no secrets leave
this repo" guarantee holds everywhere. gitleaks can still run as a CI safety net
on GitHub's runners.

pre-commit passes the staged file paths as arguments. Exit 1 on any finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# High-signal patterns — tuned for low false-positive rate.
RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("Slack webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")),
    ("Discord webhook", re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Stripe secret key", re.compile(r"\bsk_live_[0-9A-Za-z]{24,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}\b")),
    (
        "Hardcoded credential assignment",
        re.compile(
            r"""(?ix)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*['"]([^'"\s]{12,})['"]"""
        ),
    ),
]

# Substrings that mark a match as an obvious placeholder, not a real secret.
PLACEHOLDERS = (
    "your-", "your_", "xxx", "changeme", "change-me", "example", "placeholder",
    "dummy", "redacted", "<", "${", "{{", "sk-secret-key-here", "sk-hardcoded-secret",
    "todo", "fixme", "test-token", "fake",
)

# Files/paths that are templates or documentation by design.
ALLOW_PATH = re.compile(
    r"(^|[\\/])(\.env\.(example|sample|template)|package-lock\.json)$"
    r"|[\\/]\.claude[\\/]skills[\\/]security[\\/].*\.md$"
    r"|[\\/]scripts[\\/]hooks[\\/]scan-secrets\.py$"
)

BINARY_SNIFF = b"\x00"
MAX_BYTES = 1_500_000  # skip anything larger than ~1.5 MB


def is_placeholder(value: str) -> bool:
    low = value.lower()
    return any(p in low for p in PLACEHOLDERS)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    findings: list[tuple[int, str, str]] = []
    try:
        raw = path.read_bytes()
    except OSError:
        return findings
    if not raw or len(raw) > MAX_BYTES or BINARY_SNIFF in raw[:4096]:
        return findings
    text = raw.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for label, pattern in RULES:
            m = pattern.search(line)
            if not m:
                continue
            captured = m.group(1) if m.groups() else m.group(0)
            if is_placeholder(captured):
                continue
            findings.append((lineno, label, line.strip()[:120]))
    return findings


def main(argv: list[str]) -> int:
    total = 0
    for arg in argv[1:]:
        path = Path(arg)
        if not path.is_file() or ALLOW_PATH.search(str(path)):
            continue
        for lineno, label, snippet in scan_file(path):
            if total == 0:
                sys.stderr.write("\n\033[31m✗ Potential secret(s) found in staged files:\033[0m\n")
            total += 1
            sys.stderr.write(f"  {path}:{lineno}  [{label}]\n      {snippet}\n")

    if total:
        sys.stderr.write(
            f"\n  {total} potential secret(s). If a real secret leaked, rotate it now.\n"
            "  If it's a false positive, add it to the allowlist in scan-secrets.py\n"
            "  or .gitleaks.toml — do not bypass with --no-verify.\n\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
