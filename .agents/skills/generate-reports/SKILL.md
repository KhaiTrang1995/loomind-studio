---
name: generate-reports
description: Generate Experience Engine statistics and performance reports. Use after task runs or for project status overview.
---

Generate reports for the Loomind Experience Engine.

## Check engine stats
```bash
curl -s http://localhost:8082/api/stats | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('=== Loomind Engine Stats ===')
print(f'  Total experiences: {d[\"total_experiences\"]}')
print(f'  Total queries:     {d[\"total_queries\"]}')
print(f'  Avg latency:       {d[\"avg_latency_ms\"]:.1f}ms')
print(f'  Queries today:     {d[\"queries_today\"]}')
"
```

## Check health status
```bash
curl -s http://localhost:8082/health | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('=== Engine Health ===')
print(f'  Status:    {d[\"status\"]}')
print(f'  Qdrant:    {\"✅\" if d[\"qdrant\"] else \"❌\"}')
print(f'  Embedder:  {\"✅\" if d[\"embedder_loaded\"] else \"❌\"}')
print(f'  LLM:       {\"✅\" if d[\"llm_available\"] else \"❌ (optional)\"}')
print(f'  Uptime:    {d[\"uptime_seconds\"]:.0f}s')
print(f'  Version:   {d[\"version\"]}')
"
```

## Export experience data
```bash
curl -s http://localhost:8082/api/experiences/backup/export | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'Total experiences: {d[\"total\"]}')
print(f'Engine version: {d[\"engine_version\"]}')
print(f'Exported at: {d[\"exported_at\"]}')
"
```

## After generating
Report the engine stats, health status, and total experiences. If engine is not running, inform the user.
