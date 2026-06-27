# Loomind Studio — Project Instructions

## Commands

### TypeScript (Monorepo)
- Install: `npm install`
- Build all: `npx turbo build`
- Dev server: `npm run dev -w apps/loomind-desktop`
- Lint: `npx turbo lint`
- Format: `prettier --write "**/*.{js,ts,tsx,json,css,html}"`

### Python (Experience Engine)
- Setup: `cd core/loomind-engine && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`
- Start engine: `python -m uvicorn src.main:app --host 0.0.0.0 --port 8082`
- Test: `python -m pytest tests/ -v --cov=src`
- Seed data: `python seed_data.py`

### Docker
- Start: `cd apps/docker-deployment && docker compose up -d`

### Desktop (Tauri)
- Dev: `npm run tauri:dev -w apps/loomind-desktop`
- Build: `python build_all.py`

## Architecture

**Polyglot monorepo** — Python + TypeScript + Rust:

```
core/loomind-engine/     🐍 FastAPI — 3-layer intercept pipeline (L1 filter → L2 semantic search → L3 LLM)
packages/loomind-types/  📘 Shared TypeScript type definitions
packages/loomind-client/ 📘 SDK client + offline queue + L1 filter
apps/loomind-desktop/    ⚛️ React + Tauri — native dashboard
apps/loomind-cli/        📘 CLI tool (status, list, add, search, delete, export, import)
apps/docker-deployment/      🐳 Docker Compose (Engine + Qdrant)
extensions/vscode/           📘 VS Code Extension — Copilot hooks
deployment/systemd/          📦 Linux systemd service
```

## Key Files
- `core/loomind-engine/src/main.py` — FastAPI app factory & lifespan
- `core/loomind-engine/src/domain/experience_service.py` — 3-layer pipeline logic
- `core/loomind-engine/src/domain/models.py` — Pydantic v2 schemas
- `core/loomind-engine/src/infrastructure/qdrant_client.py` — Qdrant vector store
- `core/loomind-engine/src/infrastructure/embedder.py` — Sentence-Transformers embedder
- `core/loomind-engine/src/infrastructure/llm_client.py` — Ollama/llama.cpp Layer 3
- `core/loomind-engine/src/presentation/` — FastAPI routers
- `packages/loomind-client/src/api.ts` — TypeScript SDK
- `apps/loomind-desktop/src/App.tsx` — React dashboard
- `apps/loomind-desktop/src-tauri/src/lib.rs` — Tauri sidecar lifecycle
- `build_all.py` — PyInstaller + Tauri NSIS installer

## API Endpoints (Engine at :8082)
- `POST /api/intercept` — Main: 3-layer pipeline, returns suggestions
- `GET/POST /api/experiences` — CRUD experiences
- `POST /api/experiences/search` — Semantic search
- `POST /api/experiences/{id}/feedback` — Upvote/downvote
- `GET/POST /api/experiences/backup/export|import` — Backup & restore
- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe
- `GET /api/stats` — Engine statistics

## Rules
- Python: type hints (Pydantic v2 for models), async FastAPI routes
- TypeScript: strict mode, tsup for bundling, Turborepo for orchestration
- Use DDD structure for engine: domain/ → infrastructure/ → presentation/
- Experience Engine data flows: InterceptRequest → L1 → L2 → L3 → InterceptResponse
- Qdrant uses `query_points()` (v1.17+), not `search()`
- Never commit `.env` — use `.env.example`
- Engine tests in `core/loomind-engine/tests/`
- Commits: keep only the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` attribution trailer. Do **not** add a `Claude-Session:` trailer — it is unnecessary and must not appear in commit history.

## AI Agent Integration
- Full integration guide: `docs/ai-assistant-instructions.md`
- AI agents should call `POST /api/intercept` before write actions
- Save user lessons via `POST /api/experiences`
- Send feedback via `POST /api/experiences/{id}/feedback`
