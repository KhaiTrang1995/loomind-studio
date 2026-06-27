"""
Authentication middleware — Bearer token verification on mutating endpoints.

Verifies Authorization header on POST/PUT/PATCH/DELETE /api/* routes.
Returns 401 with generic error (don't reveal which check failed).
Disabled when AUTH_SECRET_KEY is empty (dev mode).

Requirements: 11.2
"""

from __future__ import annotations

import hmac
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token auth middleware for mutating API endpoints."""

    def __init__(self, app, secret_key: str = "") -> None:
        super().__init__(app)
        self.secret_key = secret_key
        self.enabled = bool(secret_key)

    async def dispatch(self, request: Request, call_next):
        # Skip if auth disabled
        if not self.enabled:
            return await call_next(request)

        # Only check mutating methods on /api/ routes
        if request.method not in MUTATING_METHODS:
            return await call_next(request)

        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Verify Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing credentials"},
            )

        token = auth_header[7:]  # strip "Bearer "
        if not token or not hmac.compare_digest(token, self.secret_key):
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing credentials"},
            )

        return await call_next(request)
