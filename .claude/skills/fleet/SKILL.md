---
description: View the Loomind CLI agent fleet and approve HITL tasks
argument-hint: [approve <goal_id> <task_id>]
disable-model-invocation: false
---

If `$ARGUMENTS` starts with "approve", parse goal_id and task_id from the arguments and run:
```bash
curl -s -X POST "http://127.0.0.1:8082/api/ba/goals/{goal_id}/tasks/{task_id}/approve" \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'
```
Report whether the approval succeeded or failed, then stop.

Otherwise, run all three commands and gather the results:

```bash
curl -s --max-time 4 http://127.0.0.1:8082/health
curl -s --max-time 4 "http://127.0.0.1:8082/api/agents/fleet"
curl -s --max-time 4 "http://127.0.0.1:8082/api/ba/goals?limit=20"
```

Display the results as follows:

**Engine status** — show `status` field from `/health` (or "OFFLINE" if curl failed).

**Fleet** — render a table from `/api/agents/fleet`. Columns: CLI Name | Status | Current Task | Tasks Done | Last Seen. If the fleet array is empty or the endpoint failed, print "No CLIs online."

**HITL Pending** — from `/api/ba/goals`, list any tasks where `status == "hitl_pending"`. For each, show: `goal_id` | `task_id` | goal title | task description. If none, print "No tasks awaiting approval." If the user needs to approve one, they can run: `/fleet approve <goal_id> <task_id>`
