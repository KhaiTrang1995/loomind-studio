#!/usr/bin/env python3
"""Codex SessionStart hook — loads project context at session launch."""

import json
import sys
from pathlib import Path


def main():
    data = json.load(sys.stdin)
    cwd = data.get("cwd", ".")

    context_parts = [
        "Loomind Studio — polyglot monorepo (Python + TypeScript + Rust).",
        "core/loomind-engine/ = FastAPI Experience Engine with 3-layer intercept pipeline.",
        "packages/ = TypeScript shared types + SDK client.",
        "apps/ = Desktop (Tauri+React), CLI, Docker deployment.",
        "extensions/vscode/ = VS Code extension for AI agent hooks.",
    ]

    # Check if engine exists
    engine_path = Path(cwd) / "core" / "loomind-engine" / "src" / "main.py"
    if engine_path.exists():
        context_parts.append("Engine entry: core/loomind-engine/src/main.py")

    # Check agent availability
    import shutil

    for tool in ["claude", "codex", "gemini"]:
        if shutil.which(tool):
            context_parts.append(f"Agent available: {tool}")

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": " ".join(context_parts),
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
