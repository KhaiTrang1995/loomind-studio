"""
File-based log store for the Experience Engine.
Writes structured logs to disk for the desktop app log viewer.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileStore:
    """Simple file-based store for logs and data export."""

    def __init__(self, log_dir: str = "./logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def write_log(self, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        """Write a structured log entry to the log file."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
        }
        if data:
            entry["data"] = data

        log_file = self.log_dir / f"engine-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_logs(self, date: str | None = None, level: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Read log entries from disk."""
        target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.log_dir / f"engine-{target_date}.log"

        if not log_file.exists():
            return []

        entries = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if level and entry.get("level") != level:
                        continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue

        return entries[-limit:]

    def export_experiences(self, experiences: list[dict[str, Any]], filename: str = "experiences_export.json") -> str:
        """Export experiences to a JSON file."""
        export_path = self.log_dir / filename
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(experiences, f, indent=2, default=str)
        return str(export_path)
