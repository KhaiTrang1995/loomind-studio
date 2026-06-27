"""
Configuration module for Loomind Engine.
Uses pydantic-settings to load from environment variables and .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Engine
    engine_host: str = Field(default="127.0.0.1", description="Host to bind the server")
    engine_port: int = Field(default=8082, description="Port to bind the server")
    engine_log_level: str = Field(default="info", description="Log level")

    # Qdrant
    qdrant_mode: str = Field(default="local", description="Qdrant mode: 'local' or 'server'")
    qdrant_path: str = Field(default="./data/qdrant", description="Path for Qdrant local mode storage")
    qdrant_url: str = Field(default="http://localhost:6333", description="URL for Qdrant server mode")
    qdrant_collection: str = Field(default="experiences", description="Qdrant collection name")

    # Embeddings
    embedding_model: str = Field(default="all-MiniLM-L6-v2", description="Sentence-Transformers model name")
    embedding_device: str = Field(default="cpu", description="Device for embeddings: 'cpu' or 'cuda'")

    # LLM (Anti-Noise Filter)
    llm_provider: str = Field(default="ollama", description="LLM provider: 'ollama' or 'llamacpp'")
    ollama_url: str = Field(default="http://localhost:11434", description="Ollama API URL")
    ollama_model: str = Field(default="llama3.2:3b", description="Ollama model name")
    llamacpp_url: str = Field(default="http://localhost:8080", description="llama.cpp API URL")

    # Logging
    log_format: str = Field(default="json", description="Log format: 'json' or 'console'")
    log_file: str = Field(default="./logs/engine.log", description="Log file path")

    # Auth — empty means disabled (dev mode)
    auth_secret_key: str = Field(default="", description="Bearer auth secret; empty = disabled")

    # Rate limiting
    extract_rate_limit: int = Field(default=60, description="Max /api/extract requests per 60s window")
    intercept_rate_limit: int = Field(default=120, description="Max /api/intercept requests per 60s window per client IP")

    # Background worker
    enable_judge_worker: bool = Field(default=True, description="Enable judge background worker")
    judge_batch_interval: float = Field(default=5.0, description="Judge queue poll interval (seconds)")
    judge_batch_size: int = Field(default=16, description="Max items per judge batch")
    evolve_interval_minutes: int = Field(default=30, description="Evolution cycle interval (minutes)")

    # Signing key for principle sharing (HMAC-SHA256)
    principle_signing_key: str = Field(default="", description="HMAC key for principle bundles; empty = unsigned")

    # Agentic Brain — Phase 11
    hitl_timeout_seconds: int = Field(default=180, description="Seconds to wait for HITL approval before auto-execute")
    max_task_retries: int = Field(default=3, description="Max task retries before escalating to HITL")
    goal_db_path: str = Field(default="./data/goals.db", description="SQLite path for goal/task persistence")
    notification_enabled: bool = Field(default=False, description="Feature flag: enable webhook/Telegram notifications")
    telegram_bot_token: str = Field(default="", description="Telegram bot token (v2 feature)")
    telegram_chat_id: str = Field(default="", description="Telegram chat ID for notifications (v2 feature)")

    # Multi-CLI Fleet — Phase 12
    cli_timeout_seconds: int = Field(default=300, description="Max seconds for one headless CLI execution")
    deliberation_max_rounds: int = Field(default=3, description="Max deliberation rounds before HITL escalation")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


# Singleton settings instance
settings = Settings()
