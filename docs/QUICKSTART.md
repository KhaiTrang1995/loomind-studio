# Loomind Studio — Quick Start & Architecture

## One-Command Start

```bash
# From repo root (Git Bash on Windows)
bash start.sh

# Skip nexus-kb
bash start.sh --no-nexus

# Skip frontend (engine only)
bash start.sh --no-frontend

# Custom nexus-kb path
NEXUS_KB_PATH=D:/your/path/nexus-kb bash start.sh
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Loomind Studio                          │
│                  Autonomous Multi-CLI Brain                      │
└─────────────────────────────────────────────────────────────────┘

                         ┌──────────────┐
                         │   Frontend   │
                         │  React+Vite  │
                         │  :5173       │
                         │              │
                         │  Fleet ─────────── CLI cards, deliberations
                         │  Graph ─────────── agent network (live)
                         │  Terminal ──────── real-time CLI output
                         │  Experiences ───── knowledge base
                         │  Goals ─────────── task decomposition
                         └──────┬───────┘
                                │ SSE (live) + REST
                                ▼
         ┌──────────────────────────────────────────────────┐
         │              Loomind Engine                  │
         │              FastAPI + Uvicorn  :8082             │
         │                                                   │
         │  3-Layer Intercept Pipeline                       │
         │    L1: Read-only filter (0ms)                     │
         │    L2: Semantic search via Qdrant (<50ms)         │
         │    L3: LLM relevance filter (<500ms)              │
         │                                                   │
         │  Phase 11 — Agentic Brain                         │
         │    BA Agent, HITL, SQLite goal store              │
         │    GoalService → task decomposition               │
         │    EventBus → SSE broadcast                       │
         │                                                   │
         │  Phase 12 — Multi-CLI Fleet                       │
         │    CLIRegistry  → fleet status                    │
         │    CLIExecutor  → headless subprocess runner      │
         │    DeliberationService → consensus engine         │
         │      SECURITY keywords → HITL (mandatory)        │
         │      ≥60% agree + conf≥0.7 → auto-resolve        │
         │      resolve → auto-save Experience               │
         └──────┬─────────────────────────────────────────┬─┘
                │                                         │
                ▼                                         ▼
    ┌───────────────────┐                    ┌────────────────────┐
    │   Qdrant          │                    │   SQLite           │
    │   Vector DB :6333 │                    │   Goal Store       │
    │                   │                    │   (goals.db)       │
    │   collections:    │                    └────────────────────┘
    │   - experiences   │
    │   - exp_t0..t3    │
    │   - observations  │
    └───────────────────┘

CLI Fleet (registered via hooks, run on HOST):
  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │ Claude  │  │  Grok   │  │  Codex  │  │   AGY   │
  │ :hook   │  │ :hook   │  │ :wrap   │  │ :wrap   │
  │ orange  │  │ purple  │  │  blue   │  │  green  │
  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
       │             │             │             │
       └─────────────┴─────────────┴─────────────┘
                     │ PATCH /api/agents/{cli}/status
                     │ POST  /api/deliberate (when stuck)
                     ▼
             Loomind Engine

nexus-kb (D:/Github/nexus-kb, separate repo):
  ┌──────────────────────────────────────────┐
  │  nexus-kb API  :8001                     │
  │  FastAPI — knowledge graph service       │
  │                                          │
  │  tsx_bridge.py → Loomind at :8082    │
  │    intercept()       before writes       │
  │    save_experience() after graph build   │
  │    deliberate()      for arch decisions  │
  └──────────────────────────────────────────┘
```

---

## Services

| Service | Port | How to Start | Purpose |
|---------|------|--------------|---------|
| Loomind Engine | 8082 | `docker compose up -d` (in `apps/docker-deployment`) | Brain — intercept, learn, deliberate |
| Qdrant Vector DB | 6333 | Same Docker Compose | Vector storage for experiences |
| Frontend Dashboard | 5173 | `npm run dev -w apps/loomind-desktop` | Visualization — Fleet, Graph, Terminal |
| nexus-kb API | 8001 | `uvicorn nexus_api.main:app --port 8001` (in nexus-kb) | Knowledge graph service |

---

## Automation Loop

```
User runs CLI (Grok at nexus-kb)
  │
  ├─► Grok hook → PATCH /api/agents/grok/status (busy)
  │       → Fleet Monitor: Grok card turns amber
  │
  ├─► nexus-kb API: POST /api/v1/graph/build
  │       → tsx_bridge.intercept() → suggestions from experience base
  │       → GraphBuildService runs entity extraction
  │       → tsx_bridge.save_experience() → Qdrant (knowledge saved)
  │
  ├─► Need a decision? POST /api/v1/deliberate (from nexus-kb)
  │       → Loomind starts deliberation
  │       → CLIs online? → headless subprocess + collect votes
  │       → CLIs offline? → HITL pending (appears in Fleet Council Room)
  │       → Resolved → auto-save Experience with consensus
  │
  └─► Grok hook → PATCH /api/agents/grok/status (idle/offline)
          → Fleet Monitor: Grok card returns to online/offline
```

---

## Fleet Monitor Pages

### `/fleet` — Fleet Monitor
- **CLI Fleet cards**: real-time status (online/busy/idle/offline) for all 4 CLIs
- **Start Deliberation panel**: type topic + context → CLIs deliberate → see result in Council Room
- **CLI Live Output**: streaming stdout from deliberation rounds
- **Council Room**: all deliberations (open/resolved/HITL) with round-by-round reasoning and confidence scores

### `/graph` — Agent Graph
- Circular force graph showing:
  - **AgentRegistry nodes** (registered sessions/bots) in colored circles by role
  - **CLI fleet nodes** (claude/grok/codex/agy) with their brand colors
  - **Edges**: message flows (blue solid), deliberation links (blue "deliberate"), shared goal links (gray dashed)
- Click a node to select; send messages between agents

### `/terminal` — Live Engine Log
- Real-time Python log output from every engine component
- CLI subprocess stdout appears here during deliberations (filter by `cli_*` module)
- Level filter (DEBUG/INFO/WARNING/ERROR) + module quick-filter chips

### `/experiences` — Knowledge Base
- Browse/search all saved experiences
- Deliberation outcomes auto-appear here with `[Deliberation]` title prefix and `deliberation` category

---

## CLI Hook Setup

For CLIs to report live status to the Fleet Monitor:

### Claude (this session hooks)
```json
// .claude/settings.local.json — already set up
// Hooks fire on UserPromptSubmit → busy, Stop → idle
```

### Grok
```toml
# ~/.grok/config.toml — already set up
# Hooks fire on session start/stop
```

### Codex + AGY
```powershell
# Run in PowerShell (any terminal):
. $PROFILE     # load wrapper functions
# Then use `codex` and `agy` commands normally
```

See `docs/fleet-hooks/` for example config files.

---

## nexus-kb Integration

```bash
# Install httpx in nexus-kb venv (one-time)
.venv/Scripts/pip install httpx

# Set TSX_ENGINE_URL if engine is not at localhost:8082
export TSX_ENGINE_URL=http://localhost:8082

# Run nexus-kb API with Loomind bridge active
cd D:/Github/nexus-kb/services/nexus-api
.venv/Scripts/python -m uvicorn nexus_api.main:app --host 0.0.0.0 --port 8001
```

**nexus-kb endpoints enhanced by Loomind:**
- `POST /api/v1/ingest` — intercepts before embedding, saves ingest outcome as experience
- `POST /api/v1/graph/build` — intercepts before build (get suggestions), saves entity/edge counts
- `POST /api/v1/deliberate` — triggers multi-CLI deliberation visible in Fleet Council Room

**Disable bridge:** Set `TSX_ENABLED=0` in environment.

---

## Deliberation Trigger (from any CLI or script)

```bash
# Trigger deliberation directly (engine API)
curl -X POST http://localhost:8082/api/deliberate \
  -H "Content-Type: application/json" \
  -d '{"from_cli": "nexus-kb", "topic": "Should we use confidence threshold 0.7 or 0.8 for entity extraction?", "context": "Phase 4 graph builder"}'

# Response: {"deliberation_id": "...", "status": "open|hitl_pending"}
# Monitor at: http://localhost:5173/fleet (Council Room section)
```

```bash
# From nexus-kb API
curl -X POST http://localhost:8001/api/v1/deliberate \
  -H "Content-Type: application/json" \
  -d '{"topic": "nexus-kb architecture: PostgreSQL vs SQLite for metadata?", "context": "Current phase 2, 10k docs expected"}'
```

---

## Phase History

| Phase | What | Where |
|-------|------|-------|
| 0-8 | 3-layer intercept, Qdrant, evolution, judge, graph, timeline, routing | `core/loomind-engine` |
| 9 | Harness Brain: agent registry, goal decomposition, SSE, MCP tools | `core/…/agents_router.py`, `goals_router.py` |
| 10 | VS Code extension Copilot hooks | `extensions/vscode/` |
| 11 | Agentic Brain: BA Agent, HITL (180s), SQLite WAL, notifications | `core/…/ba_router.py`, `goal_store.py` |
| 12 | Multi-CLI Fleet: CLIExecutor, CLIRegistry, DeliberationService | `core/…/deliberation/` |
| 12+ | nexus-kb ↔ Loomind bridge, auto-experience from deliberations | `nexus-kb/tsx_bridge.py` |

---

## Key Files

```
core/loomind-engine/
  src/domain/deliberation/deliberation_service.py  ← consensus engine + auto-experience
  src/infrastructure/cli_executor.py               ← headless subprocess + stdout streaming
  src/infrastructure/cli_registry.py               ← fleet status tracker
  src/presentation/deliberation_router.py          ← POST /api/deliberate
  src/presentation/agents_router.py                ← GET /api/agents/graph (shows CLIs)
  src/presentation/stream_router.py                ← SSE /api/stream/fleet

apps/loomind-desktop/src/pages/
  Fleet.tsx                                        ← CLI cards, Deliberate panel, Council Room
  Graph.tsx                                        ← agent + CLI network graph
  Terminal.tsx                                     ← live engine + CLI log

D:/Github/nexus-kb/services/nexus-api/nexus_api/
  tsx_bridge.py                                    ← Loomind integration (intercept/deliberate)
  main.py                                          ← v0.2.0 with bridge hooks
```
