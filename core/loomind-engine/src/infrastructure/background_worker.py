"""
Background Worker — In-process asyncio task manager.

- Judge queue: pulls from logs/jobs/judge.jsonl every 5s, batches up to 16.
- Evolve cron: runs EvolutionService.run_cycle every N minutes.
- File-backed durable queue surviving restarts.
- Auto-restart on crash within 5s, replay unprocessed items.
- Back-pressure: reject at 10,000 queue depth, resume at 8,000.

Requirements: 3.1, 3.2, 3.7, 3.8
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.domain.models import JudgeItem, Observation

logger = logging.getLogger(__name__)

QUEUE_DIR = Path("./logs/jobs")
JUDGE_QUEUE_FILE = QUEUE_DIR / "judge.jsonl"
BACKPRESSURE_HIGH = 10_000
BACKPRESSURE_LOW = 8_000


class BackgroundWorker:
    """In-process asyncio task manager for judge queue and evolve cron."""

    def __init__(
        self,
        judge_service: Any,
        evolution_service: Any,
        *,
        batch_interval: float = 5.0,
        batch_size: int = 16,
        evolve_interval_minutes: int = 30,
        qdrant: Any = None,
    ) -> None:
        self.judge_service = judge_service
        self.evolution_service = evolution_service
        self.qdrant = qdrant  # QdrantStore for observation persistence
        self.batch_interval = batch_interval
        self.batch_size = batch_size
        self.evolve_interval = evolve_interval_minutes * 60
        self._judge_task: Optional[asyncio.Task] = None
        self._evolve_task: Optional[asyncio.Task] = None
        self._running = False
        self._queue_depth = 0
        self._backpressure_active = False

        # Ensure queue directory exists
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def judge_worker_status(self) -> str:
        if self._judge_task is None:
            return "stopped"
        if self._judge_task.done():
            return "error" if self._judge_task.exception() else "stopped"
        return "running"

    @property
    def evolve_cron_status(self) -> str:
        if self._evolve_task is None:
            return "stopped"
        if self._evolve_task.done():
            return "error" if self._evolve_task.exception() else "stopped"
        return "running"

    @property
    def queue_depth(self) -> int:
        return self._queue_depth

    async def start(self) -> None:
        """Start the judge queue and evolve cron tasks."""
        self._running = True
        self._judge_task = asyncio.create_task(self._judge_loop(), name="judge_worker")
        self._evolve_task = asyncio.create_task(self._evolve_loop(), name="evolve_cron")
        logger.info("BackgroundWorker started (judge every %.1fs, evolve every %dm)",
                     self.batch_interval, self.evolve_interval // 60)

    async def stop(self) -> None:
        """Stop all background tasks."""
        self._running = False
        for task in (self._judge_task, self._evolve_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("BackgroundWorker stopped")

    async def enqueue_judge(self, item: JudgeItem) -> str:
        """Enqueue a judge item. Returns job_id. Raises if backpressure active."""
        self._update_queue_depth()

        if self._backpressure_active and self._queue_depth >= BACKPRESSURE_LOW:
            raise BackpressureError(f"Queue depth {self._queue_depth} exceeds threshold")

        if self._queue_depth >= BACKPRESSURE_HIGH:
            self._backpressure_active = True
            raise BackpressureError(f"Queue depth {self._queue_depth} exceeds {BACKPRESSURE_HIGH}")

        job_id = f"job_{item.trace_id}_{item.suggestion_id}"
        entry = {
            "job_id": job_id,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "processed": False,
            **item.model_dump(),
        }

        with open(JUDGE_QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        self._queue_depth += 1
        if self._queue_depth < BACKPRESSURE_LOW:
            self._backpressure_active = False

        return job_id

    # ── Judge loop ─────────────────────────────────────────────────────

    async def _judge_loop(self) -> None:
        """Pull from judge queue every batch_interval seconds."""
        # Initial delay to let the system warm up
        await asyncio.sleep(2.0)

        while self._running:
            try:
                items = self._dequeue_batch()
                if items:
                    observations: list[Observation] = await self.judge_service.judge_batch(items)
                    # Persist observations for evolution cycle to consume
                    if self.qdrant is not None:
                        for obs in observations:
                            try:
                                self.qdrant.store_observation(obs)
                            except Exception:
                                logger.exception("Failed to persist observation %s", obs.id)
                    self._mark_processed(len(items))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Judge loop error; will retry in 5s")
                await asyncio.sleep(5.0)
                continue

            await asyncio.sleep(self.batch_interval)

    def _dequeue_batch(self) -> list[JudgeItem]:
        """Read unprocessed items from the queue file."""
        if not JUDGE_QUEUE_FILE.exists():
            return []

        items: list[JudgeItem] = []
        try:
            with open(JUDGE_QUEUE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("processed"):
                            continue
                        items.append(JudgeItem(
                            trace_id=data["trace_id"],
                            suggestion_id=data["suggestion_id"],
                            action_taken=data["action_taken"],
                            transcript_snippet=data.get("transcript_snippet"),
                        ))
                        if len(items) >= self.batch_size:
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            logger.exception("Failed to read judge queue")

        return items

    def _mark_processed(self, count: int) -> None:
        """Mark the first N unprocessed items as processed."""
        if not JUDGE_QUEUE_FILE.exists():
            return

        try:
            lines = JUDGE_QUEUE_FILE.read_text(encoding="utf-8").splitlines()
            marked = 0
            new_lines = []
            for line in lines:
                if marked < count:
                    try:
                        data = json.loads(line)
                        if not data.get("processed"):
                            data["processed"] = True
                            marked += 1
                        new_lines.append(json.dumps(data))
                    except (json.JSONDecodeError, KeyError):
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            JUDGE_QUEUE_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            self._queue_depth = max(0, self._queue_depth - count)
        except Exception:
            logger.exception("Failed to mark processed")

    def _update_queue_depth(self) -> None:
        """Count unprocessed items in the queue file."""
        if not JUDGE_QUEUE_FILE.exists():
            self._queue_depth = 0
            return

        count = 0
        try:
            with open(JUDGE_QUEUE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if not data.get("processed"):
                            count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass
        self._queue_depth = count

    # ── Evolve loop ────────────────────────────────────────────────────

    async def _evolve_loop(self) -> None:
        """Run evolution cycle every evolve_interval seconds."""
        # First cycle 5 min after startup
        await asyncio.sleep(300)

        while self._running:
            try:
                report = await self.evolution_service.run_cycle()
                logger.info("Evolve cron completed: %s", report.model_dump())
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Evolve cron error; will retry next cycle")

            await asyncio.sleep(self.evolve_interval)


class BackpressureError(Exception):
    """Raised when the judge queue exceeds back-pressure threshold."""
    pass
