---
description: Save a lesson learned or pattern to the Loomind Experience Engine
argument-hint: [quick description of what you learned]
disable-model-invocation: false
---

# /experience — Capture a Lesson to the Engine

**Goal:** Persist a lesson, pattern, bug-fix, or decision to the engine's vector store so it surfaces in future intercept suggestions for all agents.

## Steps

### 1. Gather input

If `$ARGUMENTS` is provided, treat it as the description/context for the experience.

Ask the user (or infer from current conversation context) for:
- **Title** — one concise line, max 80 chars (e.g. "Qdrant v1.17+ requires query_points not search")
- **Description** — 2–4 sentences explaining the lesson, what went wrong, and how to avoid it
- **Category** — one of: `pattern` | `bug` | `security` | `performance` | `architecture` | `workflow`
- **Severity** — `info` (good-to-know) | `warning` (avoid this) | `critical` (always apply)
- **Tags** — 2–4 comma-separated keywords relevant to this lesson

If `$ARGUMENTS` is a full sentence you can infer title, category, and severity from context and only confirm with the user before saving.

### 2. Save to engine

Run this Bash command (substitute values, escape JSON properly):

```bash
curl -s -X POST http://127.0.0.1:8082/api/experiences \
  -H "Content-Type: application/json" \
  -d '{
    "title": "<TITLE>",
    "description": "<DESCRIPTION>",
    "category": "<CATEGORY>",
    "severity": "<SEVERITY>",
    "tags": [<TAGS_AS_JSON_ARRAY>]
  }'
```

### 3. Confirm

If the response contains an `id` field, report:
```
[OK] Experience saved: <id>
     Title: <title>
     Category: <category> | Severity: <severity>
     Tags: <tags>
     Will surface in L2 semantic search for relevant future actions.
```

If the engine is unreachable (connection refused), tell the user:
```
[FAIL] Engine offline — start with: cd apps/docker-deployment && docker compose up -d
       Or for dev: python -m uvicorn src.main:app --port 8082
```

## Tips
- Capture experiences immediately after discovering them — context is richest right now
- `critical` severity experiences are promoted to L1 keyword filter after enough upvotes
- Use `architecture` category for structural decisions (e.g. "use DDD pattern for engine layers")
- Use `workflow` category for process lessons (e.g. "always run tsc --noEmit before commit")
