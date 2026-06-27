"""
Log Broadcaster — intercepts Python log records and forwards them as SSE 'log' events.

Wire up with setup_log_broadcasting(event_bus) in main.py lifespan after EventBus
is created. Broadcasts to all SSE subscribers so the desktop Terminal page receives
live engine output.

Recursion guard: prevents event_bus.broadcast() → logger.warning() → broadcast() loop.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.event_bus import EventBus

_handler: "_SSELogHandler | None" = None
_in_emit: bool = False  # recursion guard (single event-loop thread)


class _SSELogHandler(logging.Handler):
    """Logging handler that pushes records to EventBus as SSE 'log' events."""

    def __init__(self, event_bus: "EventBus") -> None:
        super().__init__()
        self._bus = event_bus

    def emit(self, record: logging.LogRecord) -> None:
        global _in_emit
        if _in_emit:
            return
        _in_emit = True
        try:
            self._bus.broadcast({
                "event": "log",
                "payload": {
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                },
            })
        except Exception:
            pass  # never raise from a logging handler
        finally:
            _in_emit = False


def setup_log_broadcasting(event_bus: "EventBus", min_level: int = logging.INFO) -> None:
    """Install the SSE log handler on the root logger (idempotent)."""
    global _handler
    if _handler is not None:
        return
    h = _SSELogHandler(event_bus)
    h.setLevel(min_level)
    logging.getLogger().addHandler(h)
    _handler = h


def teardown_log_broadcasting() -> None:
    """Remove the SSE log handler (call on engine shutdown)."""
    global _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler = None
