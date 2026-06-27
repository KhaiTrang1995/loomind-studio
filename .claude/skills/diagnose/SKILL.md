---
description: Diagnose the Loomind stack — engine, Qdrant, Docker, and fleet health
disable-model-invocation: false
---

Run all checks in parallel using a single Bash call (store each response; a curl failure means that service is offline):

```bash
curl -s --max-time 4 http://127.0.0.1:8082/health        # engine liveness
curl -s --max-time 4 http://127.0.0.1:8082/ready          # engine readiness
curl -s --max-time 4 http://127.0.0.1:8082/api/stats      # engine stats
curl -s --max-time 4 http://127.0.0.1:8082/api/agents/fleet  # agent fleet
curl -s --max-time 4 http://127.0.0.1:6333/healthz        # Qdrant
cd D:/GitHub/loomind-studio/apps/docker-deployment && docker compose ps 2>&1  # Docker
```

Summarize results in three sections:

**Healthy** — list each service that responded successfully.

**Degraded** — list services that responded but reported non-healthy status (e.g., engine `status != "ok"`, readiness checks failing, stats showing high error rates).

**Offline** — list services with no response or curl timeout.

Then provide **Suggested Fixes** only for degraded or offline items, using exactly these recommendations:
- Engine offline → `cd apps/docker-deployment && docker compose up -d`
- Engine up but `/ready` failing → Qdrant or embedder not ready; check Qdrant container logs: `docker compose logs qdrant`
- Qdrant unreachable (port 6333) → `docker compose ps` to confirm qdrant container is running; if not: `docker compose up -d qdrant`
- Docker not running → Start Docker Desktop, then `cd apps/docker-deployment && docker compose up -d`
- Fleet empty → No CLI agents connected; launch a CLI agent or check `apps/loomind-cli/` config
- Stats show high error rate → Check engine logs: `docker compose logs loomind-engine --tail 50`
