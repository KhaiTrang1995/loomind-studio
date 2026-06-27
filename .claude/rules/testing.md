---
paths:
  - "core/loomind-engine/tests/**/*.py"
  - "**/*.test.ts"
  - "**/*.spec.ts"
---

# Testing Rules

## Python (Experience Engine)
- Tests live in `core/loomind-engine/tests/`
- Use `pytest` with `--cov=src` for coverage
- Mock external services: Qdrant, Ollama, Sentence-Transformers
- Use `tmp_path` fixture for filesystem tests, not `tempfile` directly
- Assert specific values: `assert data["key"] == "expected"` not `assert data`

## TypeScript (Packages & Apps)
- Build verification via `npx turbo build`
- Type checking is implicit through `tsup` builds with `--dts`
- All packages must compile without errors
