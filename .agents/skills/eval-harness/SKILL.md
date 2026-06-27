---
name: eval-harness
description: Run the Experience Engine evaluation harness to measure suggestions quality, skip rates, and latency.
---

Evaluate the accuracy and latency of the Loomind Experience Engine.

## Steps

1. Start the Experience Engine:
```bash
cd core/loomind-engine
python -m uvicorn src.main:app --host 0.0.0.0 --port 8082
```

2. Run the evaluation harness script:
```bash
python core/loomind-engine/src/harness/evaluator.py --url http://127.0.0.1:8082
```

3. Read the generated report:
The evaluator script generates a detailed markdown report at docs/eval-report.md. View this file to inspect skip accuracy, average F1-score, and latency statistics.

## When to Run
Run this harness:
- After modifying Qdrant experiences database (importing/seeding new data) to ensure suggestions relevance.
- After updating the Layer 1 read-only filter commands list.
- To benchmark response times when switching embedding models or LLM providers.
