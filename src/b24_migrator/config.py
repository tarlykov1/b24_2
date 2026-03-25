from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.exc import ArgumentError
from sqlalchemy.engine import URL, make_url

from b24_migrator.errors import AppError


class PortalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    webhook: str


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_mode: Literal["production", "dev", "test"] = Field(
        default="production",
        description="Runtime mode. production enforces MySQL-only storage backend.",
    )
    database_url: str = Field(description="SQLAlchemy DSN for runtime state")
    source: PortalConfig
    target: PortalConfig
    default_scope: list[str] = Field(default_factory=lambda: ["crm", "tasks"])

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            make_url(value)
        except ArgumentError as exc:
            raise ValueError("database_url must be a valid SQLAlchemy URL") from exc
        return value

    @model_validator(mode="after")
    def validate_storage_policy(self) -> RuntimeConfig:
        engine_name = database_engine_name(self.database_url)
        if self.runtime_mode == "production" and engine_name != "mysql":
            raise ValueError(
                "production/runtime storage is MySQL-only; use runtime_mode=dev|test for explicit non-production override"
            )
        return self


def database_engine_name(database_url: str) -> str:
    url: URL = make_url(database_url)
    backend = url.get_backend_name()
    return backend.lower()


def is_mysql_url(database_url: str) -> bool:
    return database_engine_name(database_url) == "mysql"


def _load_yaml_module() -> Any:
    if importlib.util.find_spec("yaml") is None:
        raise AppError(
            code="CONFIG_DEPENDENCY_MISSING",
            message="PyYAML is required to read migration.config.yml",
            details={"dependency": "PyYAML", "install": "pip install PyYAML"},
        )
    return importlib.import_module("yaml")


def _apply_env_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "MIGRATION_RUNTIME_MODE": ("runtime_mode",),
        "MIGRATION_DATABASE_URL": ("database_url",),
        "MIGRATION_SOURCE_BASE_URL": ("source", "base_url"),
        "MIGRATION_SOURCE_WEBHOOK": ("source", "webhook"),
        "MIGRATION_TARGET_BASE_URL": ("target", "base_url"),
        "MIGRATION_TARGET_WEBHOOK": ("target", "webhook"),
    }
    data = {**payload}
    data.setdefault("source", {})
    data.setdefault("target", {})

    for env_key, path in mapping.items():
        env_value = os.getenv(env_key)
        if not env_value:
            continue
        cursor: dict[str, Any] = data
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = env_value
    return data


def load_runtime_config(config_path: Path) -> RuntimeConfig:
    """Load runtime config from YAML and env overrides."""

    if not config_path.exists():
        raise AppError(
            code="CONFIG_NOT_FOUND",
            message="Config file was not found",
            details={"path": str(config_path)},
        )

    yaml = _load_yaml_module()
    with config_path.open("r", encoding="utf-8") as fh:
        try:
            raw_payload = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            raise AppError(
                code="CONFIG_YAML_PARSE_ERROR",
                message="Config file is not valid YAML",
                details={"path": str(config_path), "error": str(exc)},
            ) from exc

    payload = _apply_env_overrides(raw_payload)

    try:
        return RuntimeConfig.model_validate(payload)
    except ValidationError as exc:
        raise AppError(
            code="CONFIG_VALIDATION_ERROR",
            message="Invalid runtime config",
            details={"errors": exc.errors()},
        ) from exc
