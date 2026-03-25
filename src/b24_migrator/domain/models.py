from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class Job:
    """Top-level migration job grouping multiple plans."""

    job_id: str
    source_portal: str
    target_portal: str
    created_at: datetime


@dataclass(slots=True, frozen=True)
class Plan:
    """Deterministic migration plan belonging to a job."""

    plan_id: str
    job_id: str
    source_portal: str
    target_portal: str
    scope: list[str]
    deterministic_hash: str
    created_at: datetime


@dataclass(slots=True, frozen=True)
class Run:
    """Execution snapshot for a plan run."""

    plan_id: str
    run_id: str
    status: str
    processed_items: int
    checkpoint_token: str | None


@dataclass(slots=True, frozen=True)
class Checkpoint:
    """Persisted run checkpoint with optional serialized runtime state."""

    checkpoint_id: int | None
    run_id: str
    checkpoint_token: str
    state: dict[str, Any] | None
    created_at: datetime


@dataclass(slots=True, frozen=True)
class LogEntry:
    """Runtime log entry bound to a run."""

    log_id: int | None
    run_id: str
    level: str
    message: str
    created_at: datetime


# Backward-compatible aliases used across existing services/tests.
MigrationPlan = Plan
ExecutionResult = Run
