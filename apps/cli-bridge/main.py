"""
CLI Bridge — Host-side HTTP server that proxies CLI subprocess calls.

Config: apps/cli-bridge/config.json (auto-created on first run)
  GET  /config          → read current config
  PATCH /config         → update + save (frontend calls this)
  GET  /health          → status per CLI
  POST /cli/{name}/enable | /disable  → runtime toggle (also saves to config)
  POST /cli/{name}      → run CLI headlessly, return output

Usage:
    python -m uvicorn main:app --host 0.0.0.0 --port 8083
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Loomind CLI Bridge", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config file ───────────────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).parent / "config.json"

_CONFIG_DEFAULTS: dict[str, Any] = {
    "enabled_clis":   ["claude", "grok", "agy"],
    "cli_timeout":    120,
    "poll_interval":  15,
    "max_iterations": 3,
    "engine_url":     "http://localhost:8082",
    "cli_paths":      {"claude": "", "grok": "", "agy": "", "codex": ""},
}


def _load_config() -> dict[str, Any]:
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            # Merge with defaults so new keys are always present
            merged = {**_CONFIG_DEFAULTS, **data}
            merged["cli_paths"] = {**_CONFIG_DEFAULTS["cli_paths"], **data.get("cli_paths", {})}
            return merged
        except Exception:
            pass
    return dict(_CONFIG_DEFAULTS)


def _save_config(cfg: dict[str, Any]) -> None:
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


_config: dict[str, Any] = _load_config()

# ── CLI binary resolution ─────────────────────────────────────────────────────

_ALL_CLIS = ["claude", "grok", "agy", "codex"]

_CLI_HEADLESS_FLAGS: dict[str, list[str]] = {
    "claude": ["--print"],
    "grok":   ["-p"],
    "agy":    ["--print"],
    "codex":  ["exec"],
}


def _resolve_binary(cli: str) -> str:
    """Resolve CLI binary: config path → env var → PATH → ~/.local/bin."""
    # 1. config.json cli_paths
    cfg_path = _config.get("cli_paths", {}).get(cli, "")
    if cfg_path and os.path.isfile(cfg_path):
        return cfg_path

    # 2. Env var override
    env_key = f"{cli.upper()}_CMD"
    if os.getenv(env_key):
        return os.environ[env_key]

    # 3. PATH
    found = shutil.which(cli)
    if found:
        return found

    # 4. ~/.local/bin (Windows standalone installers)
    local_bin = Path.home() / ".local" / "bin"
    for ext in (".exe", ".cmd", ""):
        candidate = local_bin / (cli + ext)
        if candidate.is_file():
            return str(candidate)

    return cli  # fallback — subprocess will fail with clear error


def _build_cmd(cli: str, prompt: str) -> list[str]:
    binary = _resolve_binary(cli)
    flags = _CLI_HEADLESS_FLAGS.get(cli, ["--print"])
    return [binary] + flags + [prompt]


def _is_available(cli: str) -> bool:
    binary = _resolve_binary(cli)
    return shutil.which(binary) is not None or os.path.isfile(binary)


def _is_enabled(cli: str) -> bool:
    return cli in _config.get("enabled_clis", [])

# ── Models ────────────────────────────────────────────────────────────────────

class CLIRequest(BaseModel):
    prompt: str
    timeout: int = 0  # 0 = use config value
    cwd: str | None = None  # working directory for subprocess (worktree support)


class CLIResponse(BaseModel):
    cli: str
    output: str
    exit_code: int
    duration_ms: float
    success: bool
    available: bool
    enabled: bool


class ConfigPatch(BaseModel):
    enabled_clis:   list[str] | None = None
    cli_timeout:    int | None = None
    poll_interval:  int | None = None
    max_iterations: int | None = None
    engine_url:     str | None = None
    cli_paths:      dict[str, str] | None = None


# ── Config endpoints ──────────────────────────────────────────────────────────

@app.get("/config")
def get_config() -> dict:
    """Return full config + per-CLI status (for frontend Settings page)."""
    cli_status = {
        cli: {
            "available": _is_available(cli),
            "enabled":   _is_enabled(cli),
            "binary":    _resolve_binary(cli),
        }
        for cli in _ALL_CLIS
    }
    return {**_config, "cli_status": cli_status}


@app.patch("/config")
def patch_config(body: ConfigPatch) -> dict:
    """Update config fields and persist to config.json."""
    global _config
    if body.enabled_clis is not None:
        _config["enabled_clis"] = [c for c in body.enabled_clis if c in _ALL_CLIS]
    if body.cli_timeout is not None:
        _config["cli_timeout"] = max(10, body.cli_timeout)
    if body.poll_interval is not None:
        _config["poll_interval"] = max(5, body.poll_interval)
    if body.max_iterations is not None:
        _config["max_iterations"] = max(1, min(10, body.max_iterations))
    if body.engine_url is not None:
        _config["engine_url"] = body.engine_url.rstrip("/")
    if body.cli_paths is not None:
        _config["cli_paths"] = {**_config.get("cli_paths", {}), **body.cli_paths}
    _save_config(_config)
    return get_config()


# ── Enable / disable endpoints ────────────────────────────────────────────────

@app.post("/cli/{cli_name}/enable")
def enable_cli(cli_name: str) -> dict:
    if cli_name not in _ALL_CLIS:
        raise HTTPException(status_code=400, detail=f"Unknown CLI: {cli_name}")
    enabled = list(_config.get("enabled_clis", []))
    if cli_name not in enabled:
        enabled.append(cli_name)
    _config["enabled_clis"] = enabled
    _save_config(_config)
    return {"ok": True, "cli": cli_name, "enabled": True, "available": _is_available(cli_name)}


@app.post("/cli/{cli_name}/disable")
def disable_cli(cli_name: str) -> dict:
    if cli_name not in _ALL_CLIS:
        raise HTTPException(status_code=400, detail=f"Unknown CLI: {cli_name}")
    _config["enabled_clis"] = [c for c in _config.get("enabled_clis", []) if c != cli_name]
    _save_config(_config)
    return {"ok": True, "cli": cli_name, "enabled": False}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    cli_status = {
        cli: {"available": _is_available(cli), "enabled": _is_enabled(cli)}
        for cli in _ALL_CLIS
    }
    available_clis = {
        cli: info["available"] and info["enabled"]
        for cli, info in cli_status.items()
    }
    return {"ok": True, "available_clis": available_clis, "cli_status": cli_status}


@app.get("/cli/{cli_name}/available")
def check_available(cli_name: str) -> dict:
    if cli_name not in _ALL_CLIS:
        return {"cli": cli_name, "available": False, "enabled": False}
    return {
        "cli":       cli_name,
        "available": _is_available(cli_name),
        "enabled":   _is_enabled(cli_name),
        "active":    _is_available(cli_name) and _is_enabled(cli_name),
        "binary":    _resolve_binary(cli_name),
    }


# ── Host file tree (for frontend file picker) ─────────────────────────────────

_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    "dist", "build", ".next", ".turbo", "coverage", ".pytest_cache",
    ".ruff_cache", ".cargo", "target", ".idea", ".vscode",
}
_IGNORE_EXTS = {".pyc", ".pyo", ".class", ".o"}
_MAX_PER_DIR = 200


def _walk(root: Path, depth: int, max_depth: int) -> list[dict]:
    if depth > max_depth:
        return []
    items: list[dict] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return []
    count = 0
    for entry in entries:
        if count >= _MAX_PER_DIR:
            items.append({"name": "… (truncated)", "path": "", "type": "info"})
            break
        if entry.name.startswith(".") and entry.name not in {".env.example", ".gitignore"}:
            if entry.is_dir():
                continue
        if entry.is_dir():
            if entry.name in _IGNORE_DIRS:
                continue
            items.append({
                "name": entry.name,
                "path": str(entry),
                "type": "dir",
                "children": _walk(entry, depth + 1, max_depth),
            })
        elif entry.is_file():
            if entry.suffix.lower() in _IGNORE_EXTS:
                continue
            items.append({"name": entry.name, "path": str(entry), "type": "file"})
        count += 1
    return items


@app.get("/files")
def list_files(root: str = Query(..., description="Absolute path on host to browse")) -> dict:
    """Return a nested file tree for the given host path (used by Goals file picker)."""
    p = Path(root)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Path does not exist: {root}")
    if not p.is_dir():
        raise HTTPException(status_code=422, detail=f"Not a directory: {root}")
    return {"root": str(p), "tree": _walk(p, 0, 3)}


# ── Run CLI ───────────────────────────────────────────────────────────────────

@app.post("/cli/{cli_name}", response_model=CLIResponse)
async def run_cli(cli_name: str, body: CLIRequest) -> CLIResponse:
    if cli_name not in _ALL_CLIS:
        raise HTTPException(status_code=400, detail=f"Unknown CLI: {cli_name}")
    if not _is_enabled(cli_name):
        raise HTTPException(status_code=503, detail=f"{cli_name} is disabled — enable via Settings or POST /cli/{cli_name}/enable")
    if not _is_available(cli_name):
        raise HTTPException(status_code=503, detail=f"{cli_name} binary not found. Set path in Settings or config.json.")

    cmd = _build_cmd(cli_name, body.prompt)
    timeout = body.timeout or _config.get("cli_timeout", 120)
    t0 = datetime.now(timezone.utc).timestamp()
    cwd = body.cwd if body.cwd and os.path.isdir(body.cwd) else None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
        assert proc.stdout is not None
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            ms = (datetime.now(timezone.utc).timestamp() - t0) * 1000
            return CLIResponse(cli=cli_name, output="[TIMEOUT]", exit_code=-1,
                               duration_ms=ms, success=False, available=True, enabled=True)

        ms = (datetime.now(timezone.utc).timestamp() - t0) * 1000
        return CLIResponse(
            cli=cli_name,
            output=stdout.decode(errors="replace"),
            exit_code=proc.returncode or 0,
            duration_ms=ms,
            success=(proc.returncode == 0),
            available=True,
            enabled=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
