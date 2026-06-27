"""
Notification Service — Feature-flagged webhook/Telegram push notifications.

Architecture: feature flag OFF by default. Toggled via UI or MCP tool.
v1: generic webhook POST support.
v2: Telegram Bot API (stub ready, activation requires token + chat_id).

Phase 11 — Agentic Brain.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from src.domain.models import NotificationConfig

logger = logging.getLogger(__name__)


class NotificationService:
    """Sends task progress notifications to configured webhooks/Telegram."""

    def __init__(self, config: Optional[NotificationConfig] = None) -> None:
        self._config = config or NotificationConfig()
        self._client = httpx.AsyncClient(timeout=5.0)

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def get_config(self) -> NotificationConfig:
        return self._config

    def update_config(self, update: dict) -> NotificationConfig:
        """Partial update of notification config."""
        current = self._config.model_dump()
        for k, v in update.items():
            if v is not None and k in current:
                current[k] = v
        self._config = NotificationConfig(**current)
        logger.info("Notification config updated: enabled=%s", self._config.enabled)
        return self._config

    def set_enabled(self, enabled: bool) -> None:
        self._config.enabled = enabled
        logger.info("Notification feature flag: %s", "ON" if enabled else "OFF")

    async def notify_task_started(self, task_num: int, description: str) -> None:
        msg = f"[Loomind] ⚙️ Task #{task_num} đang thực hiện: {description}"
        await self._send(msg)

    async def notify_task_hitl(self, task_num: int, description: str, timeout_s: int) -> None:
        msg = f"[Loomind] ⏳ Task #{task_num} cần xác nhận: {description}. Tự động sau {timeout_s}s."
        await self._send(msg)

    async def notify_task_escalated(self, task_num: int) -> None:
        msg = f"[Loomind] ▶️ Task #{task_num} tự thực hiện (không có phản hồi)."
        await self._send(msg)

    async def notify_task_completed(self, task_num: int, description: str) -> None:
        msg = f"[Loomind] ✅ Task #{task_num} hoàn thành: {description}"
        await self._send(msg)

    async def notify_goal_done(self, goal_text: str) -> None:
        msg = f"[Loomind] 🎉 Goal hoàn thành: {goal_text[:100]}"
        await self._send(msg)

    async def notify_goal_failed(self, goal_text: str, reason: str) -> None:
        msg = f"[Loomind] ❌ Goal thất bại: {goal_text[:80]} — {reason[:80]}"
        await self._send(msg)

    # ── Private ──────────────────────────────────────────────────────────

    async def _send(self, message: str) -> None:
        if not self._config.enabled:
            return

        # Generic webhooks
        for url in self._config.webhook_urls:
            try:
                await self._client.post(url, json={"text": message}, timeout=5.0)
            except Exception as exc:
                logger.warning("Webhook %s failed: %s", url, exc)

        # Telegram (v2 — requires bot_token + chat_id)
        if self._config.telegram_bot_token and self._config.telegram_chat_id:
            await self._send_telegram(message)

    async def _send_telegram(self, message: str) -> None:
        token = self._config.telegram_bot_token
        chat_id = self._config.telegram_chat_id
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            resp = await self._client.post(url, json={"chat_id": chat_id, "text": message})
            if resp.status_code != 200:
                logger.warning("Telegram send failed: %s", resp.text[:200])
        except Exception as exc:
            logger.warning("Telegram error: %s", exc)

    async def aclose(self) -> None:
        await self._client.aclose()
