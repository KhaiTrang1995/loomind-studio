"""
Save real experiences learned from our coding session into the engine.
These are ACTUAL lessons, not demo data.
"""

import json
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

ENGINE_URL = "http://localhost:8082"

# Real experiences from this session
REAL_EXPERIENCES = [
    {
        "title": "Qdrant 1.17+ uses query_points() instead of search()",
        "description": "Qdrant client version 1.17+ REMOVED the .search() method entirely. Must use .query_points() instead. New API: client.query_points(collection_name=name, query=vector, limit=top_k, score_threshold=threshold, query_filter=filter). Access results via results.points (not iterating results directly). Old API client.search(query_vector=...) is GONE and will raise AttributeError.",
        "category": "bug",
        "severity": "critical",
        "tags": ["qdrant", "python", "api-migration", "breaking-change", "vector-database"]
    },
    {
        "title": "Windows PowerShell cp1252 cannot print emoji characters",
        "description": "Python scripts on Windows PowerShell that print emoji (checkmark, cross mark) cause UnicodeEncodeError with cp1252 codec. Fix: set environment variable before running: $env:PYTHONIOENCODING='utf-8' or use sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8'). Alternative: avoid emoji in console output, use ASCII equivalents like [OK] [FAIL].",
        "category": "bug",
        "severity": "warning",
        "tags": ["windows", "powershell", "encoding", "unicode", "python"]
    },
    {
        "title": "Tauri 2.0 CSP blocks localhost API calls by default",
        "description": "Tauri 2.0 WebView enforces Content Security Policy. fetch() calls to localhost:8082 are blocked unless CSP is configured in tauri.conf.json. Required: connect-src 'self' http://localhost:8082. For Google Fonts: style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com.",
        "category": "pattern",
        "severity": "warning",
        "tags": ["tauri", "csp", "security", "desktop-app", "react"]
    },
    {
        "title": "Turborepo 2.x requires packageManager field",
        "description": "Turborepo 2.x requires the packageManager field in root package.json (e.g. npm@10.9.2). Without it, turbo will warn or fail. This ensures reproducible installs across team members. Also needed: workspaces array listing all package paths.",
        "category": "pattern",
        "severity": "info",
        "tags": ["turborepo", "monorepo", "npm", "configuration"]
    },
    {
        "title": "Sentence-Transformers cold start takes 10-60 seconds",
        "description": "First load of sentence-transformers model (all-MiniLM-L6-v2, 22MB) downloads from HuggingFace and takes 10-60s. Subsequent loads use cache (~2-5s). Cache location: ~/.cache/huggingface/. Plan for cold-start: health check should wait, show loading status to users, use lifespan event in FastAPI.",
        "category": "performance",
        "severity": "warning",
        "tags": ["sentence-transformers", "embeddings", "cold-start", "huggingface"]
    },
    {
        "title": "PowerShell uses semicolon not && for command chaining",
        "description": "PowerShell does not support && for chaining commands (bash syntax). Use semicolon instead: cmd1; cmd2; cmd3. For conditional execution use if-statement: if ($LASTEXITCODE -eq 0) { cmd2 }. This is a common gotcha when copying bash commands to Windows.",
        "category": "bug",
        "severity": "info",
        "tags": ["powershell", "windows", "shell", "scripting"]
    },
    {
        "title": "VS Code Extension MUST use CommonJS output",
        "description": "VS Code extension host requires CommonJS (CJS) module format. Set module: CommonJS in tsconfig.json and build with tsup --format cjs --external vscode. ESM output will fail at runtime. The extension.ts entry point MUST be bundled as CJS. Use @types/vscode for type definitions.",
        "category": "pattern",
        "severity": "critical",
        "tags": ["vscode", "extension", "commonjs", "typescript", "bundling"]
    },
    {
        "title": "Vite proxy config eliminates CORS issues in dev mode",
        "description": "React app on port 5173 calling FastAPI on port 8082 triggers CORS errors. Fix: configure Vite proxy in vite.config.ts: server.proxy = { '/api': 'http://localhost:8082' }. All fetch('/api/...') calls are proxied. In production, enable CORS on FastAPI with allow_origins=['*'] or serve from same origin.",
        "category": "pattern",
        "severity": "info",
        "tags": ["vite", "cors", "proxy", "react", "fastapi"]
    },
    {
        "title": "Use full .venv Python path on Windows for reliability",
        "description": "On Windows, always use full path to .venv Python executable: d:/project/.venv/Scripts/python.exe -m uvicorn. Do NOT rely on bare 'python' command as it may resolve to system Python, conda base, or wrong version. The .venv/Scripts/activate only works in current shell session and is NOT inherited by subprocesses or background commands.",
        "category": "bug",
        "severity": "warning",
        "tags": ["windows", "python", "venv", "virtual-environment", "path"]
    },
    {
        "title": "Refresh PATH in PowerShell after tool installation",
        "description": "After installing Rust, Node.js, or other tools that modify system PATH, current PowerShell session does NOT see the change. Must manually refresh: $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User'). Alternative: open new terminal.",
        "category": "bug",
        "severity": "warning",
        "tags": ["powershell", "windows", "path", "environment", "rust"]
    },
    {
        "title": "Docker multi-stage build reduces Python image 5x",
        "description": "Python Docker images with pip/Poetry dependencies can reach 1.5GB. Use multi-stage build: Stage 1 (builder) installs all deps, Stage 2 (runtime) copies only site-packages and source. Result: ~300MB. Also create non-root user (useradd loomind) for security. Base: python:3.10-slim (not python:3.10 which includes build tools).",
        "category": "performance",
        "severity": "info",
        "tags": ["docker", "multi-stage", "image-size", "python", "security"]
    },
    {
        "title": "Qdrant local mode needs no Docker for development",
        "description": "Qdrant supports embedded/local mode: QdrantClient(path='./data/qdrant'). Data stored in local SQLite-like folder. No Docker, no server needed. Perfect for development. Switch to server mode QdrantClient(url='http://localhost:6333') for production via Docker. Control with QDRANT_MODE env var (local/server).",
        "category": "pattern",
        "severity": "info",
        "tags": ["qdrant", "development", "docker", "local-mode"]
    },
    {
        "title": "Docker Desktop on Windows requires WSL 2 backend",
        "description": "Docker Desktop on Windows uses WSL 2 as its default virtualization backend. If WSL is not installed, Docker Desktop fails to start. Fix: Run 'wsl --install' in Administrator PowerShell and restart Windows.",
        "category": "bug",
        "severity": "critical",
        "tags": ["docker", "windows", "wsl2", "troubleshooting"]
    },
    {
        "title": "Poetry install fails in Docker if referenced README.md is not copied",
        "description": "If pyproject.toml defines a readme file (e.g. readme = 'README.md'), poetry install will fail if the file is not copied in the build stage. Fix: Copy both pyproject.toml and README.md into the Docker image before running poetry install.",
        "category": "bug",
        "severity": "critical",
        "tags": ["poetry", "docker", "python", "pyproject.toml"]
    },
    {
        "title": "PowerShell blocks script-based npm execution",
        "description": "PowerShell Script Execution Policy restricts running npm.ps1 by default. Fix: Use npm.cmd instead of npm in PowerShell commands, or run commands with Bypass execution policy (e.g., -ExecutionPolicy Bypass).",
        "category": "bug",
        "severity": "warning",
        "tags": ["powershell", "windows", "npm", "execution-policy"]
    },
]


def save():
    # Health check
    try:
        r = requests.get(f"{ENGINE_URL}/health", timeout=5)
        print(f"Engine: {r.json()['status']}")
    except Exception as e:
        print(f"Engine offline: {e}")
        return

    saved = 0
    for exp in REAL_EXPERIENCES:
        try:
            r = requests.post(f"{ENGINE_URL}/api/experiences", json=exp, timeout=15)
            if r.status_code == 200:
                print(f"  [OK] {exp['title'][:60]}")
                saved += 1
            else:
                print(f"  [FAIL] {r.status_code}: {exp['title'][:60]}")
        except Exception as e:
            print(f"  [ERR] {exp['title'][:40]}: {e}")

    print(f"\nSaved: {saved}/{len(REAL_EXPERIENCES)}")

    # Verify total
    r = requests.get(f"{ENGINE_URL}/api/stats", timeout=5)
    print(f"Total experiences in engine: {r.json()['total_experiences']}")


if __name__ == "__main__":
    save()
