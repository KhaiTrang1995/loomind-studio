#!/usr/bin/env python3
"""
Sync nexus-kb review queue -> Loomind goals.
Usage: python scripts/sync_nexus_reviews.py [--dry-run] [--watch]
  --dry-run: print what would be submitted, don't actually POST
  --watch: loop every 60s
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NEXUS_URL = os.getenv("NEXUS_API_URL", "http://127.0.0.1:8000")
TSX_URL = os.getenv("TSX_ENGINE_URL", "http://127.0.0.1:8082")
REVIEW_QUEUE_LIMIT = int(os.getenv("NEXUS_REVIEW_LIMIT", "50"))
WATCH_INTERVAL = int(os.getenv("NEXUS_WATCH_INTERVAL", "60"))

# State file lives alongside the script so it follows the repo, not cwd.
_SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = _SCRIPT_DIR.parent / "data" / ".nexus_sync_state.json"


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def _get(url: str, headers: Optional[dict] = None) -> Any:
    """GET url, return parsed JSON.  Raises urllib.error.URLError on failure."""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _post(url: str, body: dict) -> Any:
    """POST JSON body to url, return parsed JSON.  Raises on failure."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    """Load the set of already-synced nexus item IDs from disk."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Could not load sync state: {exc}", file=sys.stderr)
    return {"synced_ids": []}


def _save_state(state: dict) -> None:
    """Persist the sync state to disk."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        print(f"[WARN] Could not save sync state: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

def _extract_title(item: dict) -> str:
    """
    Extract a human-readable title from a nexus-kb review queue item.
    Tries payload.qdrant_payload.title first, then falls back to first 80
    chars of content.  Uses .get() everywhere to handle shape variations.
    """
    payload = item.get("payload") or {}
    qdrant_payload = payload.get("qdrant_payload") or {}
    title = qdrant_payload.get("title") or ""
    if title and title.strip():
        return title.strip()

    # Fallback: first 80 chars of content
    content = (
        payload.get("content")
        or qdrant_payload.get("content")
        or item.get("content")
        or ""
    )
    content = str(content).strip()
    if content:
        return content[:80] + ("..." if len(content) > 80 else "")

    # Last resort: use the item id
    return f"(item {item.get('id', 'unknown')})"


def _fetch_review_queue() -> list[dict]:
    """
    Fetch pending review items from nexus-kb.
    Returns [] if nexus is offline or returns an unexpected shape.
    """
    url = f"{NEXUS_URL}/api/v1/review/queue?limit={REVIEW_QUEUE_LIMIT}"
    try:
        data = _get(url, headers={"X-User-Role": "Reviewer"})
        if isinstance(data, list):
            return data
        # Some APIs wrap in {"items": [...]} or {"data": [...]}
        if isinstance(data, dict):
            return (
                data.get("items")
                or data.get("data")
                or data.get("results")
                or []
            )
        return []
    except urllib.error.URLError as exc:
        print(f"[WARN] nexus-kb offline or unreachable ({NEXUS_URL}): {exc.reason}", file=sys.stderr)
    except Exception as exc:
        print(f"[WARN] Failed to fetch nexus review queue: {exc}", file=sys.stderr)
    return []


def _submit_goal(goal_text: str, dry_run: bool) -> Optional[str]:
    """
    POST goal to Loomind Agentic Brain.
    Returns goal_id on success, None on failure.
    """
    url = f"{TSX_URL}/api/goals"
    body = {"goal": goal_text, "submitted_by": "nexus-kb-sync"}
    if dry_run:
        return "<dry-run>"
    try:
        resp = _post(url, body)
        return (
            resp.get("goal_id")
            or resp.get("id")
            or resp.get("task_id")
            or "<unknown-id>"
        )
    except urllib.error.URLError as exc:
        print(f"[WARN] Loomind engine offline or unreachable ({TSX_URL}): {exc.reason}", file=sys.stderr)
    except Exception as exc:
        print(f"[WARN] Failed to submit goal: {exc}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Main sync pass
# ---------------------------------------------------------------------------

def run_sync(dry_run: bool) -> None:
    """Perform one sync pass.  Loads state, processes queue, saves state."""
    state = _load_state()
    already_synced: set[str] = set(state.get("synced_ids", []))

    items = _fetch_review_queue()
    if not items:
        print("No items returned from nexus-kb review queue.")
        return

    pending = [i for i in items if i.get("status") == "pending"]

    synced_count = 0
    skipped_count = 0

    for item in pending:
        item_id = str(item.get("id") or item.get("item_id") or "")
        if not item_id:
            # Can't track without an ID — skip to avoid duplicates
            print("[SKIP] Item has no id, skipping.", file=sys.stderr)
            continue

        if item_id in already_synced:
            skipped_count += 1
            continue

        title = _extract_title(item)
        goal_text = f"Review nexus-kb document: {title}"

        goal_id = _submit_goal(goal_text, dry_run=dry_run)
        if goal_id is not None:
            prefix = "[DRY-RUN]" if dry_run else "[OK]"
            print(f"{prefix} Submitted goal {goal_id}: {title}")
            if not dry_run:
                already_synced.add(item_id)
            synced_count += 1
        else:
            print(f"[FAIL] Could not submit goal for item {item_id}: {title}", file=sys.stderr)

    # Persist updated state
    if not dry_run:
        state["synced_ids"] = sorted(already_synced)
        _save_state(state)

    qualifier = " (dry-run)" if dry_run else ""
    print(f"\nSynced {synced_count} items{qualifier}, skipped {skipped_count} (already synced)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync nexus-kb review queue -> Loomind goals."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be submitted without actually POSTing.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help=f"Loop every {WATCH_INTERVAL}s (override with NEXUS_WATCH_INTERVAL env).",
    )
    args = parser.parse_args()

    if args.watch:
        print(f"[watch] Starting sync loop every {WATCH_INTERVAL}s. Ctrl+C to stop.")
        try:
            while True:
                print(f"\n--- Sync pass at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
                run_sync(dry_run=args.dry_run)
                time.sleep(WATCH_INTERVAL)
        except KeyboardInterrupt:
            print("\n[watch] Stopped.")
    else:
        run_sync(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
