---
name: health-check
description: Run Experience Engine health checks. Use when checking system status or before deployments.
---

Run health checks for the Loomind Experience Engine.

## Steps

1. Check if the engine is running:
```bash
curl -s http://localhost:8082/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d, indent=2))"
```

2. Check readiness:
```bash
curl -s http://localhost:8082/ready | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d, indent=2))"
```

3. Check engine stats:
```bash
curl -s http://localhost:8082/api/stats | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d, indent=2))"
```

## Summarize the health status
- Engine status (running/stopped)
- Qdrant connection (connected/disconnected)
- Embedder model (loaded/not loaded)
- Total experiences in database
- Uptime and version

## If engine is not running
Instruct user to start it:
```bash
cd core/loomind-engine
python -m uvicorn src.main:app --host 0.0.0.0 --port 8082
```
