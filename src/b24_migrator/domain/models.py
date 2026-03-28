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


@dataclass(slots=True, frozen=True)
class AuditEntry:
    """Audit entry for user-triggered actions."""

    audit_id: int | None
    actor: str
    action: str
    input_payload: dict[str, Any]
    outcome: str
    details: dict[str, Any] | None
    created_at: datetime


@dataclass(slots=True, frozen=True)
class MigrationMatrixEntry:
    """Supported migration matrix row."""

    entity: str
    supported_status: str
    source_module_api: str
    target_module_api: str
    dependency_prerequisites: list[str]
    mapping_strategy: str
    verification_strategy: str
    delta_support: str
    cleanup_support: str
    risk_notes: str


@dataclass(slots=True, frozen=True)
class MappingRecord:
    """Canonical source->target mapping row used by all domains."""

    mapping_id: int | None
    entity_type: str
    source_id: str
    source_uid: str | None
    target_id: str | None
    target_uid: str | None
    status: str
    resolution_strategy: str
    verification_status: str
    linked_parent_type: str | None
    linked_parent_source_id: str | None
    linked_parent_target_id: str | None
    payload_hash: str | None
    error_payload: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class UserReviewItem:
    """Ambiguous user match row requiring manual review."""

    review_id: int | None
    source_id: str
    source_uid: str | None
    candidates: list[dict[str, Any]]
    reason: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class VerificationResult:
    """Persisted verification event."""

    result_id: int | None
    run_id: str
    check_type: str
    entity_type: str
    status: str
    details: dict[str, Any]
    created_at: datetime


@dataclass(slots=True, frozen=True)
class DomainModuleStatus:
    """Migration domain lifecycle status for UI/CLI reporting."""

    domain: str
    discovery: str
    mapping: str
    migrate: str
    verify: str
    delta_support_status: str
    dependencies: list[str]


@dataclass(slots=True, frozen=True)
class DependencyStep:
    """Executable migration dependency graph step."""

    order: int
    step: str
    dependencies: list[str]


# Backward-compatible aliases used across existing services/tests.
MigrationPlan = Plan
ExecutionResult = Run
