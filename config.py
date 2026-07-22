"""
Centralised, environment-driven configuration for PowerSim AI.

All runtime configuration is read from environment variables (optionally via a
local ``.env`` file) so that no hosts, ports, model names, or secrets are
hard-coded in the application. See ``.env.example`` for the full list of
supported variables and their defaults.

Usage:
    from config import settings
    print(settings.ollama_url)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from the environment.

    Environment variables use the ``POWERSIM_`` prefix (e.g.
    ``POWERSIM_PORT=9000``). The Ollama connection variables additionally accept
    the conventional un-prefixed names (``OLLAMA_URL``, ``OLLAMA_MODEL``) so the
    app plays nicely with existing Ollama tooling and containers.
    """

    model_config = SettingsConfigDict(
        env_prefix="POWERSIM_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application -------------------------------------------------------
    app_name: str = "PowerSim AI"
    app_version: str = "2.0.0"
    environment: str = Field(
        default="development",
        description="Deployment environment: development | staging | production",
    )
    host: str = "0.0.0.0"
    port: int = 8000

    # -- Simulation --------------------------------------------------------
    simulation_seed: int = 42
    simulation_tick_seconds: float = Field(
        default=2.0, gt=0.1, description="Wall-clock seconds between simulation ticks"
    )
    telemetry_history_points: int = Field(default=120, ge=10, le=5000)
    websocket_heartbeat_seconds: float = Field(default=30.0, gt=1.0)

    # -- AI agent / Ollama LLM --------------------------------------------
    ollama_enabled: bool = True
    ollama_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("POWERSIM_OLLAMA_URL", "OLLAMA_URL"),
    )
    ollama_model: str = Field(
        default="qwen2.5:7b",
        validation_alias=AliasChoices("POWERSIM_OLLAMA_MODEL", "OLLAMA_MODEL"),
    )
    ollama_timeout_seconds: float = Field(default=30.0, gt=1.0)
    # Run the (more expensive) LLM reasoning pass at most once every N agent
    # cycles per asset; rule-based reasoning still runs every cycle. Keeps a
    # local 7B model from saturating CPU while still surfacing LLM narrative.
    agent_llm_every_n_cycles: int = Field(default=5, ge=1)
    # How often (in simulation ticks) the continuous agent loop evaluates the
    # fleet. 1 == every tick.
    agent_cycle_every_n_ticks: int = Field(default=1, ge=1)

    # -- Observability -----------------------------------------------------
    log_level: str = Field(default="INFO")
    log_json: bool = Field(
        default=False, description="Emit structured JSON logs (recommended in prod)"
    )

    # -- API hardening -----------------------------------------------------
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])
    max_ws_connections: int = Field(default=200, ge=1)

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        valid = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in valid:
            raise ValueError(f"log_level must be one of {sorted(valid)}")
        return level

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        # Allow a comma-separated string in the env var.
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth)."""
    return Settings()


settings = get_settings()
