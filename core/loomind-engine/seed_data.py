"""
Seed script — Tạo dữ liệu demo cho Experience Engine.
Chạy: python seed_data.py
"""

import requests
import sys

ENGINE_URL = "http://localhost:8082"

EXPERIENCES = [
    {
        "title": "Use Singleton Pattern for Database Connections",
        "description": "Always use a singleton or connection pool for database connections. Creating new connections on each request causes resource leaks, connection exhaustion, and performance degradation. Use SQLAlchemy's create_engine() with pool_size parameter or a dependency injection container.",
        "category": "pattern",
        "severity": "warning",
        "tags": ["database", "singleton", "connection-pool", "performance"]
    },
    {
        "title": "Never Store Secrets in Source Code",
        "description": "API keys, database passwords, JWT secrets, and other sensitive data must NEVER be committed to version control. Use environment variables (.env files), secret managers (AWS Secrets Manager, HashiCorp Vault), or CI/CD secret injection. Scan repos with tools like truffleHog or git-secrets.",
        "category": "security",
        "severity": "critical",
        "tags": ["security", "secrets", "environment-variables", "git"]
    },
    {
        "title": "Implement Error Boundaries in React",
        "description": "Wrap React component trees with Error Boundaries to catch and gracefully handle rendering errors. Without them, a single component crash can take down the entire application. Use class components with componentDidCatch() or react-error-boundary library.",
        "category": "bug",
        "severity": "warning",
        "tags": ["react", "error-handling", "frontend", "resilience"]
    },
    {
        "title": "Use Connection Pooling for HTTP Clients",
        "description": "When making HTTP requests to external APIs, reuse connections with a session/pool (requests.Session, httpx.AsyncClient, axios instance). Creating new connections per request adds TCP handshake + TLS overhead (~100-300ms). Pool connections to reduce latency by 60-80%.",
        "category": "performance",
        "severity": "info",
        "tags": ["http", "connection-pool", "latency", "performance"]
    },
    {
        "title": "Always Validate User Input Server-Side",
        "description": "Never trust client-side validation alone. Attackers can bypass JavaScript validation trivially. Always validate and sanitize input on the server using libraries like Pydantic (Python), Zod/Joi (Node.js), or Bean Validation (Java). This prevents SQL injection, XSS, and data corruption.",
        "category": "security",
        "severity": "critical",
        "tags": ["security", "validation", "input-sanitization", "xss", "sql-injection"]
    },
    {
        "title": "Use Lazy Loading for Large Data Sets",
        "description": "Don't load all data at once. Implement pagination (LIMIT/OFFSET, cursor-based), virtual scrolling for UI lists, and lazy imports for heavy modules. This dramatically reduces initial load time, memory usage, and Time-to-Interactive (TTI).",
        "category": "performance",
        "severity": "info",
        "tags": ["pagination", "lazy-loading", "virtual-scroll", "performance"]
    },
    {
        "title": "Check Null Before Accessing Nested Properties",
        "description": "TypeError: Cannot read property 'x' of undefined is the #1 JavaScript runtime error. Use optional chaining (?.), nullish coalescing (??), or explicit null checks before accessing nested object properties. TypeScript strict mode helps catch these at compile time.",
        "category": "bug",
        "severity": "warning",
        "tags": ["typescript", "null-check", "optional-chaining", "runtime-error"]
    },
    {
        "title": "Use TypeScript Strict Mode",
        "description": "Enable strict: true in tsconfig.json. This enables strictNullChecks, noImplicitAny, strictFunctionTypes and more. Catches 30-40% more bugs at compile time compared to loose mode. Every new project should start with strict mode enabled.",
        "category": "pattern",
        "severity": "info",
        "tags": ["typescript", "strict-mode", "type-safety", "best-practice"]
    },
    {
        "title": "Add Index to Frequently Queried Columns",
        "description": "If a SQL query filters by a column (WHERE, JOIN ON, ORDER BY) and takes >100ms on >10K rows, add a database index. Without indexes, the DB performs full table scans (O(n)). With indexes, it uses B-tree lookup (O(log n)). But don't over-index — each index slows writes.",
        "category": "performance",
        "severity": "warning",
        "tags": ["database", "sql", "index", "query-optimization", "performance"]
    },
    {
        "title": "Use Structured Logging Instead of print()",
        "description": "Replace print() debugging with structured logging (Python: structlog/logging, Node: pino/winston). Structured logs include timestamps, levels, context fields, and are parseable by log aggregation tools (ELK, Grafana Loki). Critical for production debugging and monitoring.",
        "category": "pattern",
        "severity": "info",
        "tags": ["logging", "observability", "debugging", "structlog"]
    },
    {
        "title": "Handle Race Conditions in Async Code",
        "description": "When multiple async operations modify shared state, use locks (asyncio.Lock), transactions (database), or optimistic concurrency control. Common symptoms: duplicate records, lost updates, inconsistent state. Test with concurrent requests using tools like locust or k6.",
        "category": "bug",
        "severity": "critical",
        "tags": ["async", "race-condition", "concurrency", "locks", "transactions"]
    },
    {
        "title": "Pin Docker Base Image Versions",
        "description": "Never use 'latest' tag for Docker base images (FROM python:latest). Pin to specific versions (FROM python:3.10-slim). Unpinned images can break builds when upstream pushes breaking changes. Use SHA256 digests for maximum reproducibility in CI/CD.",
        "category": "pattern",
        "severity": "warning",
        "tags": ["docker", "ci-cd", "reproducibility", "devops"]
    },
]


def seed():
    # Check engine health
    try:
        resp = requests.get(f"{ENGINE_URL}/health", timeout=5)
        health = resp.json()
        print(f"Engine status: {health['status']}")
        print(f"  Qdrant: {'✅' if health['qdrant'] else '❌'}")
        print(f"  Embedder: {'✅' if health['embedder_loaded'] else '❌'}")
        print(f"  LLM: {'✅' if health['llm_available'] else '❌'}")
        print()
    except Exception as e:
        print(f"❌ Cannot reach engine at {ENGINE_URL}: {e}")
        sys.exit(1)

    # Seed experiences
    success = 0
    for exp in EXPERIENCES:
        try:
            resp = requests.post(f"{ENGINE_URL}/api/experiences", json=exp, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                print(f"  ✅ Created: {data['title']}")
                success += 1
            else:
                print(f"  ❌ Failed ({resp.status_code}): {exp['title']}")
        except Exception as e:
            print(f"  ❌ Error: {exp['title']} — {e}")

    print(f"\n🎉 Seeded {success}/{len(EXPERIENCES)} experiences!")

    # Verify
    resp = requests.get(f"{ENGINE_URL}/api/stats", timeout=5)
    stats = resp.json()
    print(f"  Total experiences: {stats['total_experiences']}")

    # Test intercept
    print("\n🔍 Testing intercept pipeline...")
    resp = requests.post(f"{ENGINE_URL}/api/intercept", json={
        "action": "create database connection in db.ts",
        "action_type": "write",
        "file_path": "src/db.ts",
        "language": "typescript",
    }, timeout=10)
    data = resp.json()
    print(f"  Skipped: {data['skipped']}")
    print(f"  Suggestions: {len(data['suggestions'])}")
    print(f"  Layers: {data['layers_executed']}")
    print(f"  Latency: {data['latency_ms']:.1f}ms")
    if data['suggestions']:
        for s in data['suggestions'][:3]:
            print(f"    → [{s['severity']}] {s['title']} (score: {s['relevance_score']:.2f})")


if __name__ == "__main__":
    seed()
