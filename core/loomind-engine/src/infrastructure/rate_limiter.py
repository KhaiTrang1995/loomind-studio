"""
Rate limiter — sliding window per-token rate limiting.

60 requests per 60-second sliding window for /api/extract.
Returns 429 with Retry-After header when exceeded.

Requirements: 11.3
"""

from __future__ import annotations

import time
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class RateLimiter:
    """In-memory sliding window rate limiter."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> tuple[bool, int]:
        """Check if the request is within rate limit.

        Args:
            key: Rate limit key (e.g., Bearer token or IP).

        Returns:
            Tuple of (allowed: bool, retry_after_seconds: int).
            If allowed is False, retry_after_seconds indicates when to retry.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Clean old entries
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

        if len(self._requests[key]) >= self.max_requests:
            # Calculate retry-after
            oldest = self._requests[key][0]
            retry_after = int(oldest + self.window_seconds - now) + 1
            return False, max(retry_after, 1)

        self._requests[key].append(now)
        return True, 0
