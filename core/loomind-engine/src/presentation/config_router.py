"""
Config Router — Read and hot-patch engine configuration at runtime.

GET  /api/config  → safe subset of current settings (no secrets)
PATCH /api/config → apply changes: log level is hot-reloaded immediately;
                    everything else is saved to data/ui-settings.json and
                    takes effect on the next engine restart.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/config", tags=["config"])
logger = logging.getLogger(__name__)

_UI_SETTINGS_PATH = Path("data/ui-settings.json")

# Fields that can take effect without restarting the engine
_HOT_RELOADABLE = {"engine_log_level"}


class ConfigView(BaseModel):
    """Safe, non-secret subset of engine configuration."""
    engine_host: str
    engine_port: int
    engine_log_level: str
    qdrant_mode: str
    qdrant_path: str
    qdrant_url: str
    qdrant_collection: str
    embedding_model: str
    embedding_device: str
    llm_provider: str
    ollama_url: str
    ollama_model: str
    llamacpp_url: str
    hitl_timeout_seconds: int
    max_task_retries: int
    hot_reloadable: list[str]


class ConfigPatch(BaseModel):
    engine_log_level: Optional[str] = None
    qdrant_mode: Optional[str] = None
    qdrant_path: Optional[str] = None
    qdrant_url: Optional[str] = None
    qdrant_collection: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_device: Optional[str] = None
    llm_provider: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    llamacpp_url: Optional[str] = None
    hitl_timeout_seconds: Optional[int] = None
    max_task_retries: Optional[int] = None


def _load_overrides() -> dict:
    if _UI_SETTINGS_PATH.exists():
        try:
            return json.loads(_UI_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_overrides(data: dict) -> None:
    _UI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _UI_SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


@router.get("", response_model=ConfigView)
async def get_config(request: Request) -> ConfigView:
    """Return current engine config merged with any saved UI overrides."""
    from src.config import settings  # lazy import so router works before app init

    ov = _load_overrides()
    return ConfigView(
        engine_host=settings.engine_host,
        engine_port=settings.engine_port,
        engine_log_level=ov.get("engine_log_level", settings.engine_log_level),
        qdrant_mode=ov.get("qdrant_mode", settings.qdrant_mode),
        qdrant_path=ov.get("qdrant_path", settings.qdrant_path),
        qdrant_url=ov.get("qdrant_url", settings.qdrant_url),
        qdrant_collection=ov.get("qdrant_collection", settings.qdrant_collection),
        embedding_model=ov.get("embedding_model", settings.embedding_model),
        embedding_device=ov.get("embedding_device", settings.embedding_device),
        llm_provider=ov.get("llm_provider", settings.llm_provider),
        ollama_url=ov.get("ollama_url", settings.ollama_url),
        ollama_model=ov.get("ollama_model", settings.ollama_model),
        llamacpp_url=ov.get("llamacpp_url", settings.llamacpp_url),
        hitl_timeout_seconds=ov.get("hitl_timeout_seconds", settings.hitl_timeout_seconds),
        max_task_retries=ov.get("max_task_retries", settings.max_task_retries),
        hot_reloadable=sorted(_HOT_RELOADABLE),
    )


@router.patch("", response_model=ConfigView)
async def patch_config(body: ConfigPatch, request: Request) -> ConfigView:
    """
    Update config.  Hot-reloadable fields (engine_log_level) apply immediately.
    All others are persisted to data/ui-settings.json for the next restart.
    """
    updates = body.model_dump(exclude_none=True)

    # Hot-reload log level immediately
    if "engine_log_level" in updates:
        new_level = updates["engine_log_level"].upper()
        numeric = getattr(logging, new_level, logging.INFO)
        logging.getLogger().setLevel(numeric)
        logger.info("Log level hot-reloaded → %s", new_level)

    # Persist to disk
    existing = _load_overrides()
    existing.update(updates)
    _save_overrides(existing)
    logger.info("UI settings persisted: %s", list(updates.keys()))

    return await get_config(request)
