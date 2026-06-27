# `.codex/` — OpenAI Codex CLI Configuration

This directory configures [OpenAI Codex CLI](https://github.com/openai/codex) for the **Loomind Studio** project — a polyglot monorepo (Python + TypeScript + Rust) for the AI Experience Engine.

## Directory Structure

```
.codex/
├── config.toml            — Global Codex CLI settings
├── hooks.json             — Hook registration manifest
├── agents/                — 13 specialized sub-agents (TOML)
├── hooks/                 — 5 lifecycle hooks (Python)
└── rules/                 — 6 domain rule files
```

## `config.toml` — Global Settings

```toml
model = "o4-mini"                    # Default model
model_reasoning_effort = "medium"    # Reasoning depth

[project]
sandbox_mode = "workspace-write"     # Agents can write within workspace

[agents]
max_threads = 6                      # Max concurrent sub-agents
max_depth = 1                        # Nesting depth
job_max_runtime_seconds = 1800       # 30-min timeout
```

## Project Architecture

Loomind Studio is a **polyglot monorepo** with:

| Layer | Technology | Location |
|-------|-----------|----------|
| **Core Engine** | Python FastAPI + Qdrant + Sentence-Transformers | `core/loomind-engine/` |
| **SDK** | TypeScript (tsup) | `packages/loomind-client/` |
| **Types** | TypeScript (tsup) | `packages/loomind-types/` |
| **Desktop** | React + Tauri 2.0 (Rust) | `apps/loomind-desktop/` |
| **CLI** | TypeScript (Commander.js) | `apps/loomind-cli/` |
| **VS Code** | TypeScript Extension | `extensions/vscode/` |
| **Docker** | Docker Compose | `apps/docker-deployment/` |

## Agents

| Agent | Domain | Sandbox | Description |
|-------|--------|---------|-------------|
| `ai-ml-engineer` | AI/ML | `workspace-write` | ML pipelines, embeddings, LLM integration |
| `backend-api` | Backend | `workspace-write` | FastAPI, REST APIs, Pydantic |
| `code-reviewer` | Quality | `read-only` | Code review for correctness and style |
| `database-architect` | Data | `workspace-write` | Schema design, query optimization |
| `devops-infrastructure` | DevOps | `workspace-write` | Docker, CI/CD, deployment |
| `documentation-writer` | Docs | `workspace-write` | API docs, architecture docs |
| `explorer` | Research | `read-only` | Codebase exploration |
| `implementer` | Coding | `workspace-write` | Feature implementation, bug fixes |
| `mobile-developer` | Mobile | `workspace-write` | React Native, Flutter |
| `performance-engineer` | Performance | `workspace-write` | Profiling, optimization |
| `security-specialist` | Security | `read-only` | OWASP, vulnerability analysis |
| `test-runner` | Testing | *(default)* | Test execution, failure diagnosis |
| `web-frontend` | Frontend | `workspace-write` | React, Tauri, accessibility |

## Hooks

| Hook | Event | Purpose |
|------|-------|---------|
| **Session Start** | `SessionStart` | Loads project context and detects available tools |
| **Data Flywheel** | `UserPromptSubmit` | Injects relevant context hints |
| **Pre-Tool Policy** | `PreToolUse` | Blocks dangerous commands |
| **Post-Tool Review** | `PostToolUse` | Surfaces warnings from command output |
| **Stop/Continue** | `Stop` | Requests tests before stopping |

## Rules

| Rule File | Domain | Key Policies |
|-----------|--------|-------------|
| `default.rules` | General | Allow pytest, npm, turbo, formatters |
| `security.rules` | Security | Input validation, secrets management |
| `api.rules` | API Design | REST conventions, FastAPI patterns |
| `database.rules` | Database | Qdrant, schema design, parameterized queries |
| `aiml.rules` | AI/ML | Embeddings, vector search, LLM integration |
| `performance.rules` | Performance | Profiling, caching, async patterns |

## Related Files

| File | Purpose |
|------|---------|
| `.claude/CLAUDE.md` | Claude Code project instructions |
| `.agents/skills/` | Vendor-neutral skill library |
| `docs/ai-assistant-instructions.md` | Full AI agent API integration guide |
