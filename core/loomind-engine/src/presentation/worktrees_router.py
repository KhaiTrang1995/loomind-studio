"""
Worktrees Router — CRUD for registered repository workspaces.

GET    /api/worktrees              → list[WorktreeRecord]
POST   /api/worktrees              → WorktreeRecord (register new repo)
PATCH  /api/worktrees/{id}         → WorktreeRecord (update name/description/active)
DELETE /api/worktrees/{id}         → {"ok": true}
GET    /api/worktrees/{id}/files   → nested file tree (depth≤3, excludes noise dirs)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.domain.models import WorktreeCreateRequest, WorktreePatchRequest, WorktreeRecord

router = APIRouter(prefix="/api/worktrees", tags=["worktrees"])

_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    "dist", "build", ".next", ".turbo", "coverage", ".pytest_cache",
    ".ruff_cache", ".cargo", "target", ".idea", ".vscode",
}
_IGNORE_EXTS = {".pyc", ".pyo", ".class", ".o", ".lock"}
_MAX_FILES_PER_DIR = 200


def _walk_tree(path: Path, depth: int, max_depth: int = 3) -> list[dict[str, Any]]:
    """Recursively walk a directory and return a nested file tree."""
    if depth > max_depth:
        return []
    items: list[dict[str, Any]] = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return []
    count = 0
    for entry in entries:
        if count >= _MAX_FILES_PER_DIR:
            items.append({"name": "… (truncated)", "path": "", "type": "info"})
            break
        if entry.name.startswith(".") and entry.name not in {".env.example", ".gitignore"}:
            if entry.is_dir():
                continue
        if entry.is_dir():
            if entry.name in _IGNORE_DIRS:
                continue
            children = _walk_tree(entry, depth + 1, max_depth)
            items.append({"name": entry.name, "path": str(entry), "type": "dir", "children": children})
        elif entry.is_file():
            if entry.suffix.lower() in _IGNORE_EXTS:
                continue
            items.append({"name": entry.name, "path": str(entry), "type": "file"})
        count += 1
    return items


def _store(req: Request):
    return req.app.state.worktree_store


@router.get("", response_model=list[WorktreeRecord])
async def list_worktrees(req: Request) -> list[WorktreeRecord]:
    return _store(req).list_all()


@router.post("", response_model=WorktreeRecord, status_code=201)
async def create_worktree(body: WorktreeCreateRequest, req: Request) -> WorktreeRecord:
    return _store(req).create(body)


@router.patch("/{worktree_id}", response_model=WorktreeRecord)
async def patch_worktree(worktree_id: str, body: WorktreePatchRequest, req: Request) -> WorktreeRecord:
    record = _store(req).patch(worktree_id, body)
    if not record:
        raise HTTPException(status_code=404, detail=f"Worktree '{worktree_id}' not found")
    return record


@router.delete("/{worktree_id}")
async def delete_worktree(worktree_id: str, req: Request) -> dict:
    if not _store(req).delete(worktree_id):
        raise HTTPException(status_code=404, detail=f"Worktree '{worktree_id}' not found")
    return {"ok": True}


@router.get("/{worktree_id}/files")
async def list_worktree_files(worktree_id: str, req: Request, depth: int = 3) -> dict:
    """Return file tree — only works when engine runs on the same host as the workspace.
    In Docker deployments, use CLI Bridge GET /files?root=<path> instead (it runs on host).
    """
    record = _store(req).get(worktree_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Worktree '{worktree_id}' not found")
    root = Path(record.path)
    if not root.exists() or not root.is_dir():
        # Engine is likely in Docker and cannot access host paths.
        # Frontend should call CLI Bridge GET /files?root=<path> instead.
        return {
            "worktree_id": worktree_id,
            "root": record.path,
            "tree": [],
            "warning": (
                f"Path '{record.path}' is not accessible from the engine container. "
                "Use CLI Bridge GET /files?root=<path> (port 8083) to browse host filesystem."
            ),
        }
    max_depth = max(1, min(int(depth), 4))
    tree = _walk_tree(root, depth=0, max_depth=max_depth)
    return {"worktree_id": worktree_id, "root": str(root), "tree": tree}
