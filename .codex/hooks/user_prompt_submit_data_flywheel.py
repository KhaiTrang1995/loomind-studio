#!/usr/bin/env python3
"""Codex UserPromptSubmit hook — adds project-specific context hints."""

import json
import sys


def main():
    data = json.load(sys.stdin)
    prompt = data.get("prompt", "")

    context_hints = []

    if any(word in prompt.lower() for word in ["test", "pytest", "spec"]):
        context_hints.append(
            "Tests: cd core/loomind-engine && python -m pytest tests/ -v --cov=src. "
            "TypeScript: npx turbo build."
        )

    if any(word in prompt.lower() for word in ["api", "endpoint", "route", "intercept"]):
        context_hints.append(
            "Engine API at :8082. Key endpoints: POST /api/intercept (main pipeline), "
            "GET/POST /api/experiences (CRUD), GET /health. "
            "Routers in src/presentation/. Models in src/domain/models.py."
        )

    if any(word in prompt.lower() for word in ["qdrant", "vector", "embed", "search"]):
        context_hints.append(
            "Qdrant client: src/infrastructure/qdrant_client.py. "
            "Uses query_points() (v1.17+), NOT search(). "
            "Embedder: src/infrastructure/embedder.py (all-MiniLM-L6-v2)."
        )

    if any(word in prompt.lower() for word in ["config", "env", "setting"]):
        context_hints.append(
            "Config: core/loomind-engine/.env (copy from .env.example). "
            "Key vars: ENGINE_PORT, QDRANT_MODE, EMBEDDING_MODEL, LLM_PROVIDER."
        )

    if any(word in prompt.lower() for word in ["desktop", "tauri", "react"]):
        context_hints.append(
            "Desktop: apps/loomind-desktop/ (React + Tauri 2.0). "
            "Rust sidecar: src-tauri/src/lib.rs. Config: src-tauri/tauri.conf.json."
        )

    if any(word in prompt.lower() for word in ["docker", "deploy", "compose"]):
        context_hints.append(
            "Docker: apps/docker-deployment/docker-compose.yml. "
            "Dockerfile: apps/docker-deployment/Dockerfile. "
            "systemd: deployment/systemd/."
        )

    if context_hints:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": " ".join(context_hints),
            }
        }
        print(json.dumps(output))
    else:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
