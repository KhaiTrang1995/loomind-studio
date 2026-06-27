# Change Log

All notable changes to Loomind Studio will be documented in this file.

## [Unreleased] - 2026-06-16

### Added — Phase 12: Multi-CLI Fleet + Autonomous Deliberation

> **Goal:** Khi CLI gặp vấn đề không tự giải quyết được, thay vì hỏi người dùng, các CLIs tự prompt nhau qua engine để đạt đồng thuận rồi tiếp tục — không cần human intervention. Chỉ escalate HITL khi: (a) topic security/destructive, (b) có vote `need_human`, (c) hết max_rounds.

#### Engine — Python

- **Models Phase 12 (`src/domain/models.py`):** `CLIType` (claude/grok/codex/agy), `CLIStatus` (online/busy/idle/offline), `CLIStatusRecord`, `DeliberationVote` (agree/disagree/counter_propose/need_human/abstain), `DeliberationStatus` (open/resolved/hitl_pending/cancelled), `DeliberationRound`, `Deliberation`, `ConsultRequest`, `ConsultResponse`, `HITLResolveRequest`.

- **CLIExecutor (`src/infrastructure/cli_executor.py`):** Headless subprocess runner cho 4 CLIs. Flags xác nhận: `claude --print`, `grok -p`, `agy --print`, `codex exec`. Output stream vào EventBus → hiện live trên Terminal page. Parse vote/confidence từ JSON cuối output hoặc keyword heuristics (AGREE/DISAGREE/NEED_HUMAN). Timeout configurable.

- **CLIRegistry (`src/infrastructure/cli_registry.py`):** Fleet status tracker (online/busy/idle/offline per CLI). Task routing table: `research → grok`, `code → codex`, `review/security → claude`, `general → agy`. Security constraint: security tasks chỉ route về claude. `pick_consultants()` trả về danh sách available consultants cho deliberation.

- **DeliberationService (`src/domain/deliberation/deliberation_service.py`):** Multi-round consensus engine. Spawn consultants headless parallel qua asyncio.gather. Security keyword guard (delete/drop/secret/prod/...) → forced HITL ngay. Consensus: tất cả agree OR ≥60% agree + avg_confidence ≥ 0.7. Sau max_rounds không đồng thuận → HITL. Notify initiator qua SSE khi resolved. HITL resolve có human approve/reject.

- **Config Phase 12 (`src/config.py`):** `cli_timeout_seconds=300`, `deliberation_max_rounds=3`.

- **Deliberation Router (`src/presentation/deliberation_router.py`):**
  - `POST /api/deliberate` — CLI gửi câu hỏi, trả về ngay (async rounds chạy nền)
  - `GET /api/deliberations` — list all, newest first
  - `GET /api/deliberations/{id}` — chi tiết
  - `PATCH /api/deliberations/{id}/resolve` — human resolve HITL

- **Stream Router update (`src/presentation/stream_router.py`):** `GET /api/stream/fleet` — SSE stream cho Fleet Monitor page. Broadcast `fleet_snapshot` on connect + `fleet_status`/`deliberation_update` events live.

- **Agents Router update (`src/presentation/agents_router.py`):** `PATCH /api/agents/{id}/status` — CLIs gọi từ hooks khi status thay đổi (busy/idle/online/offline). Broadcast `fleet_status` event sau mỗi update.

- **`src/main.py`:** Khởi tạo `CLIExecutor`, `CLIRegistry`, `DeliberationService` trong lifespan. Include `deliberation_router`.

#### Frontend — React

- **`useFleet` hook (`src/hooks/useFleet.ts`):** Subscribe SSE `/api/stream/fleet`, maintain `CLIStatusRecord[]` live. CLI metadata (labels, colors) exported.
- **`useDeliberations` hook (`src/hooks/useDeliberations.ts`):** SSE + REST, expose `hitlPending`/`active`/`resolved` lists, `resolveHITL()` helper.
- **Fleet page (`src/pages/Fleet.tsx`):** CLI status cards (4 cards, color-coded per CLI), KPI row (online/busy/active deliberations/HITL count), Council Room section với deliberation cards (expandable rounds, vote badges, confidence %, HITL approve/reject panel). Route: `/fleet`.
- **`App.tsx`:** +route `/fleet`, +sidebar link "Fleet" dưới Terminal.

#### Hook Setup (auto-reporting CLI status)

- **Grok:** `~/.grok/config.toml` — `[[hooks.UserPromptSubmit]]`, `[[hooks.Stop]]`, `[[hooks.PreToolCall]]` → PATCH `/api/agents/grok/status`.
- **Claude:** `.claude/settings.local.json` (gitignored) — hooks `UserPromptSubmit`/`Stop`/`PreToolCall` → PATCH `/api/agents/claude/status`. Example: `docs/fleet-hooks/claude-settings.local.example.json`.
- **AGY:** PowerShell wrapper `scripts/fleet-hooks/tsx-agy.ps1` (gitignored) — wraps `agy.exe`, reports busy/idle automatically. Add to your `$PROFILE`.
- **Codex:** PowerShell wrapper `scripts/fleet-hooks/tsx-codex.ps1` (gitignored) — wraps `codex.exe`. Same profile.
- **Setup script:** `scripts/fleet-hooks/install-ps-profile.ps1` — idempotent, tự add function aliases vào profile.
- **Example files (tracked):** `docs/fleet-hooks/` — `claude-settings.local.example.json`, `grok-config-hooks.example.toml`, `powershell-profile.example.ps1`.

#### Git Strategy

| File | Git | Lý do |
|------|-----|-------|
| `docs/fleet-hooks/*.example.*` | ✅ tracked | Team reference |
| `scripts/fleet-hooks/` | ❌ gitignored | `scripts/` đã ignore từ trước |
| `.claude/settings.local.json` | ❌ gitignored | `.claude/settings.local.json` đã ignore |
| `~/.grok/config.toml` | ❌ outside repo | User home dir |
| PowerShell profile | ❌ outside repo | User home dir |

---

## [Unreleased] - 2026-06-14

### Added — Phase 11 Agentic Brain (Autonomous Goal Loop)

- **BA Agent (`src/domain/ba_agent/ba_service.py`):** LLM-powered goal decomposition into User Stories with
  Acceptance Criteria (Given/When/Then) and Fibonacci story points (1,2,3,5,8,13). Deterministic security
  keyword override ensures tasks with auth/token/delete keywords are forced to HITL/SECURITY regardless of
  LLM output. Heuristic fallback (research → code → test) used when LLM is unavailable.
- **GoalStore (`src/infrastructure/goal_store.py`):** SQLite WAL-mode persistence for goals and tasks.
  Atomic exclusive task claim (`UPDATE ... WHERE status='pending'`) eliminates race conditions between agents.
  Priority queue: `ORDER BY story_points DESC, created_at ASC`. Checkpoint save for resume-on-interrupt.
- **NotificationService (`src/infrastructure/notification_service.py`):** Feature-flagged push notifications.
  OFF by default — toggled via Settings UI or `toggle_notifications` MCP tool. Sends `{"text": "..."}` to
  all configured webhook URLs. Telegram Bot API (v2 stub, activated with bot_token + chat_id).
  Format: `[Loomind] ⚙️ Task #N đang thực hiện: <description>`.
- **GoalService (rewritten):** BA pipeline integrated — `analyze_and_submit()` calls BAService then persists
  via GoalStore. HITL timer (`asyncio.sleep(180)`) auto-escalates non-SECURITY tasks. SECURITY tasks never
  auto-escalate. Resume-from-checkpoint via `resume_task()`. Max 3 retries before permanent fail + HITL escalation.
- **BA Router (`src/presentation/ba_router.py`):** New endpoints:
  `POST /api/ba/analyze` (BA decomposition), `GET /api/ba/analyze/{goal_id}`,
  `POST /api/ba/goals/{id}/tasks/{tid}/approve` (HITL approval),
  `POST /api/ba/goals/{id}/tasks/{tid}/checkpoint`,
  `POST /api/ba/goals/{id}/tasks/{tid}/resume`,
  `GET/PATCH /api/ba/notifications/config`, `POST /api/ba/notifications/toggle`,
  `POST /api/ba/notifications/test`.
- **MCP Tools Phase 11 (5 new tools):** `analyze_goal`, `approve_hitl_task`, `save_task_checkpoint`,
  `toggle_notifications`, `set_webhook` — total MCP tools now 15.
- **Settings UI Phase 11:** Notification section added to `apps/loomind-desktop/src/pages/Settings.tsx`
  with feature flag toggle, webhook URL add/remove list, Telegram bot token input, and test notification button.
- **Models Phase 11 (`src/domain/models.py`):** `FIBONACCI_POINTS`, `TaskMode` enum, `AcceptanceCriteria`,
  `UserStory`, `BAAnalysisResult`, `BAAnalyzeRequest`, `HITLApproveRequest`, `NotificationConfig`,
  `NotificationConfigUpdateRequest`. Updated `TaskStatus` with `HITL_PENDING`, `IN_PROGRESS`, `INTERRUPTED`,
  `VERIFYING`. Updated `TaskRecord` with `mode`, `story_points`, `retry_count`, `checkpoint`, `hitl_deadline`.
  Updated `GoalRecord` with `analysis: Optional[dict]`.
- **Config Phase 11 (`src/config.py`):** `hitl_timeout_seconds=180`, `max_task_retries=3`,
  `goal_db_path="./data/goals.db"`, `notification_enabled=False`, `telegram_bot_token=""`, `telegram_chat_id=""`.
- **README + index.html:** Updated to document Phase 11 Agentic Brain feature set, new API endpoints,
  environment variables, and roadmap items.

### Changed — Phase 11

- `src/main.py`: lifespan now initializes `GoalStore`, `BAService`, `NotificationService`, wires them into
  `GoalService`. Includes `ba_router`. Engine version bumped to `0.3.0`. Calls `notification_service.aclose()`
  on shutdown.
- `apps/loomind-desktop/src/pages/Settings.tsx`: Added Notification section (Phase 11 Agentic Brain)
  with live API calls to `/api/ba/notifications/*`.

### Added — Phase 9 Harness Brain (Agentic Orchestration)

- **Observation persistence (Phase 9A):** `QdrantStore` now stores judge observations in a dedicated
  `exp_observations` collection via `store_observation()`, `get_unprocessed_observations()`, and
  `mark_observations_processed()`. `BackgroundWorker._judge_loop` persists observations after each batch.
- **Evolution consumes observations (Phase 9A):** `EvolutionService.run_cycle()` starts by draining
  unprocessed observations from Qdrant (verdict FOLLOWED/IGNORED drives promote/demote decisions).
  `POST /api/evolve` now accepts `batch_size` and `min_confidence` in the request body.
- **Agent Registry (Phase 9B):** `AgentRegistry` (in-memory, 120s TTL) tracks online agents by role.
  New endpoints: `POST /api/agents/register`, `POST /api/agents/heartbeat`,
  `DELETE /api/agents/{id}`, `GET /api/agents`, `GET /api/agents/{id}/tasks`.
- **Goal Decomposition (Phase 9C):** `GoalService` decomposes any natural-language goal into a fixed
  4-task pipeline: research → code → test → evaluate.  New endpoints: `POST /api/goals`,
  `GET /api/goals/{id}`, `GET /api/goals/{id}/tasks`, `POST /api/goals/{id}/tasks/{tid}/claim`,
  `POST /api/goals/{id}/tasks/{tid}/complete`, `POST /api/goals/{id}/tasks/{tid}/fail`.
- **SSE Event Bus (Phase 9D):** `EventBus` (asyncio.Queue per agent) enables real-time push.
  `GET /api/stream/{agent_id}` returns a Server-Sent Events stream. Events: `task_assigned`,
  `task_available`, `goal_completed`, `heartbeat` (every 25s to keep connection alive).
- **MCP Tools Expansion (Phase 9E):** Added 5 new tools to `src/presentation/mcp_server.py`:
  `register_agent`, `get_my_tasks`, `submit_goal`, `complete_task`, `report_posttool`.
  These call the running engine HTTP API so MCP clients share state with FastAPI.
- **SDK Async Methods (Phase 9F):** `LoomindClient` now has async counterparts for every
  operation: `aregister`, `aheartbeat`, `aintercept`, `aposttool`, `asubmit_goal`, `aclaim_task`,
  `acomplete_task`, `asubscribe` (SSE iterator). Added `agent_loop()` coroutine that handles
  register → subscribe → intercept → execute → posttool → complete in one call.
- **Agent Loop Demo (Phase 9F):** `scripts/agent_loop_template.py` — runnable 3-agent demo
  (orchestrator, researcher, coder, tester) showing the full Phase 3 Orchestrated Loop.
- **`sse-starlette>=2.0.0` and `mcp>=1.0.0`** added to `requirements.txt`.

### Changed — Phase 9

- `src/main.py` lifespan: initializes `AgentRegistry`, `EventBus`, `GoalService`, and calls
  `qdrant.ensure_observations_collection()` on startup. Passes `qdrant=qdrant` to `BackgroundWorker`.
  Includes three new routers: `agents_router`, `goals_router`, `stream_router`.
- `src/domain/models.py`: added `processed_by_evolution` to `Observation`,
  `observations_consumed` to `EvolutionReport`, and new models `AgentRole`, `AgentInfo`,
  `AgentRegisterRequest`, `TaskStatus`, `TaskRecord`, `GoalRecord`, `GoalSubmitRequest`,
  `TaskClaimRequest`, `TaskCompleteRequest`.

## [Unreleased] - 2026-06-13

### Added
- Added `INTERCEPT_RATE_LIMIT` config field (default 120 req/min) to `src/config.py`.
- Added per-IP sliding-window rate limiting on `POST /api/intercept` — returns HTTP 429 with `Retry-After` header when exceeded (`src/presentation/intercept_router.py`).
- Added `app.state.intercept_rate_limiter` initialization in `src/main.py` lifespan.
- Added `UVICORN_WORKERS` environment variable to Dockerfile and `docker-compose.yml` (default 1; increase only when BackgroundWorker file queue is replaced with Redis).
- Added `gunicorn>=22.0.0` to `requirements.txt` for future multi-process support.
- Added `extra_hosts` comment block in `docker-compose.yml` for Linux Ollama connectivity (`host.docker.internal:host-gateway`).
- Exported 29-experience knowledge base backup to `output/experiences_backup_2026-06-13.json`.

### Changed
- **Performance — Event loop unblocked:** `ExperienceService.intercept_v2()` now wraps `embedder.embed()` in `asyncio.get_running_loop().run_in_executor()`, preventing CPU-bound embedding from blocking concurrent requests.
- **Concurrency — Thread pool:** `_SEARCH_POOL` workers changed from hardcoded `3` to `min(32, cpu_count + 4)`. On a 4-core machine this yields 8 workers; the embed call now also uses this pool.
- **Multi-user correctness — Session isolation:** Replaced global `_session_seen: set[str]` (shared across all users) with `_agent_sessions: dict[str, tuple[set, float]]` keyed by agent identifier, each with a 5-minute TTL. Added `_get_session_seen()` and `_update_session_seen()` helpers; sessions prune automatically above 200 keys.
- **Docker memory:** Engine container limit increased from 1G to 2G in `docker-compose.yml`.
- **Docker CMD:** Switched from exec-form to shell-form (`sh -c`) so `UVICORN_WORKERS`, `ENGINE_PORT`, and `ENGINE_LOG_LEVEL` expand at container start. Added `--limit-concurrency 200 --backlog 2048` for async backpressure.
- **Cross-platform — evaluator.py:** Replaced `os.path.join` / `os.path.dirname` / `os.path.abspath` with `pathlib.Path` throughout `src/harness/evaluator.py`.
- **Cross-platform — docker-compose.yml:** Added `INTERCEPT_RATE_LIMIT` and `EXTRACT_RATE_LIMIT` to engine environment; added commented `extra_hosts` block for Linux Docker; explicit `ENGINE_LOG_LEVEL` env var.
- **requirements.txt:** Removed `pyinstaller` from runtime deps (build-only); added platform notes for macOS Apple Silicon / Docker / Windows.

## [Unreleased] - 2026-06-06

### Added
- Implemented Phase 8 covering Harness Engineering and Agentic Kit:
  - Created evaluation dataset at core/loomind-engine/src/harness/data/eval_dataset.json with 10 test cases.
  - Created automated evaluator script at core/loomind-engine/src/harness/evaluator.py supporting skip accuracy, precision, recall, F1, and latency benchmarking.
  - Integrated evaluation runner command (eval) into manage_experiences.py.
  - Created Model Context Protocol (MCP) Server at core/loomind-engine/src/presentation/mcp_server.py using lazy-loading for Qdrant/SentenceTransformers models, exposing tools: intercept_action, add_experience, search_experiences, get_stats, get_health.
  - Added CLI argument --mcp in launcher.py to allow running the engine binary as a stdio MCP server.
  - Created Python Client SDK and integrations (LangChain, CrewAI) at core/loomind-engine/src/client.py.
  - Added unit and integration tests for MCP server tools and Python client SDK at core/loomind-engine/tests/test_harness_mcp.py.
  - Created setup_agent.py at scripts/setup_agent.py to copy project rules to .cursorrules, .clinerules, .windsurfrules, and .github/copilot-instructions.md automatically.
  - Created example_agent.py at scripts/example_agent.py to demonstrate the Python client SDK.
  - Added vendor-neutral agent skill at .agents/skills/eval-harness/SKILL.md.
- Added Phase 8 to docs/plans/README.md.

### Changed
- Removed all emojis/icons from the root README.md to keep it clean and compliant with the icon-free guidelines, and added detailed instructions for the two AI agent integration methods (MCP and Project Rules).
- Cleaned up emojis/icons from docs/plans/README.md status table.
