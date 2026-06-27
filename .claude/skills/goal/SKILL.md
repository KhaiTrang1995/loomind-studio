---
description: Submit a high-level goal to the Loomind Agentic Brain for autonomous decomposition and execution
argument-hint: [goal description]
disable-model-invocation: false
---

# /goal — Submit a Goal to the Agentic Brain

**Goal:** Submit a high-level objective to the engine. The Brain decomposes it into tasks (research → code → test → evaluate), assigns each to the right agent, and executes autonomously with HITL checkpoints.

## Steps

### 1. Clarify the goal

If `$ARGUMENTS` is provided, use it directly as the goal text.

Otherwise ask: "What goal should the agents work on?" — one clear sentence describing the desired outcome. Good examples:
- "Add rate limiting to all /api/* endpoints in the FastAPI engine"
- "Refactor experience_service.py to separate L1/L2/L3 into independent classes"
- "Write integration tests for the deliberation router"

### 2. Submit to engine

```bash
curl -s -X POST http://127.0.0.1:8082/api/goals \
  -H "Content-Type: application/json" \
  -d '{"goal": "<GOAL_TEXT>", "submitted_by": "claude"}'
```

### 3. Display decomposed tasks

Parse the JSON response. Show:
```
[OK] Goal submitted: <goal_id>
     Goal: <goal text>
     Status: <status>

     Decomposed tasks:
     1. [research]    <task description>  → assigned to: <agent>
     2. [code]        <task description>  → assigned to: <agent>
     3. [test]        <task description>  → assigned to: <agent>
     4. [evaluate]    <task description>  → assigned to: <agent>
```

### 4. Monitor option

Ask: "Monitor progress? (y/n)"

If yes, poll `GET http://127.0.0.1:8082/api/goals/<goal_id>` every 10 seconds using a loop:

```bash
while true; do
  curl -s http://127.0.0.1:8082/api/goals/<goal_id> | python3 -c "
import json, sys
g = json.load(sys.stdin)
tasks = g.get('tasks', [])
done = sum(1 for t in tasks if t['status'] == 'completed')
hitl = sum(1 for t in tasks if t['status'] == 'hitl_pending')
running = sum(1 for t in tasks if t['status'] in ('in_progress','claimed'))
print(f'  {done}/{len(tasks)} done | {running} running | {hitl} awaiting HITL | status: {g[\"status\"]}')
if g['status'] in ('done','completed','failed'):
    print('  Goal finished.')
    sys.exit(1)
"
  [ $? -eq 1 ] && break
  sleep 10
done
```

Stop polling and summarize when `status` is `done`, `completed`, or `failed`.

### 5. HITL approval (if needed)

If any task has `status === 'hitl_pending'`, pause and tell the user:
```
[HITL] Task requires approval — run /fleet or click Approve in Dashboard
       Goal: <goal_id>   Task: <task_id>
       Description: <task description>
```

### 6. Error handling

- Engine offline → `[FAIL] Engine offline — start with: cd apps/docker-deployment && docker compose up -d`
- Goal decomposition returns empty tasks → `[WARN] Goal accepted but no tasks decomposed — check engine logs`
- Goal text too vague → suggest rewriting with a specific action verb and target file/module

## Tips
- Be specific: "Add X to Y" is better than "improve Y"
- The engine assigns tasks to agents based on task_type — research→Grok, code→Claude, test→AGY
- Goals persist in-memory — restart clears them (SQLite persistence is planned for Sprint 2)
- Use `/fleet` to monitor agent status while a goal is running
