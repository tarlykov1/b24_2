from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class MigrationPlan:
    """Immutable migration execution plan."""

    plan_id: str
    source_portal: str
    target_portal: str
    scope: list[str]
    deterministic_hash: str
    created_at: datetime


@dataclass(slots=True, frozen=True)
class ExecutionResult:
    """Result snapshot for execute/resume commands."""

    plan_id: str
    run_id: str
    status: str
    processed_items: int
    checkpoint_token: str | None
