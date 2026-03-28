from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from b24_migrator.storage.base import Base


class JobRecord(Base):
    __tablename__ = "migration_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_portal: Mapped[str] = mapped_column(String(255), nullable=False)
    target_portal: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    plans: Mapped[list[PlanRecord]] = relationship(back_populates="job", cascade="all, delete-orphan")


class PlanRecord(Base):
    __tablename__ = "migration_plans"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("migration_jobs.job_id"), nullable=False, index=True)
    source_portal: Mapped[str] = mapped_column(String(255), nullable=False)
    target_portal: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_csv: Mapped[str] = mapped_column(Text, nullable=False)
    deterministic_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    job: Mapped[JobRecord] = relationship(back_populates="plans")
    runs: Mapped[list[RunRecord]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class RunRecord(Base):
    __tablename__ = "migration_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), ForeignKey("migration_plans.plan_id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    plan: Mapped[PlanRecord] = relationship(back_populates="runs")
    checkpoints: Mapped[list[CheckpointRecord]] = relationship(back_populates="run", cascade="all, delete-orphan")
    logs: Mapped[list[LogRecord]] = relationship(back_populates="run", cascade="all, delete-orphan")
    verification_results: Mapped[list[VerificationResultRecord]] = relationship(back_populates="run", cascade="all, delete-orphan")


class CheckpointRecord(Base):
    __tablename__ = "migration_checkpoints"

    checkpoint_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("migration_runs.run_id"), nullable=False, index=True)
    checkpoint_token: Mapped[str] = mapped_column(String(128), nullable=False)
    state_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[RunRecord] = relationship(back_populates="checkpoints")


class LogRecord(Base):
    __tablename__ = "migration_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("migration_runs.run_id"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[RunRecord] = relationship(back_populates="logs")


class AuditRecord(Base):
    __tablename__ = "migration_audit"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class MappingRecordModel(Base):
    __tablename__ = "migration_mappings"
    __table_args__ = (
        UniqueConstraint("entity_type", "source_id", name="uq_migration_mappings_entity_source"),
    )

    mapping_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_uid: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    target_uid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resolution_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    linked_parent_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    linked_parent_source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    linked_parent_target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class UserReviewQueueRecord(Base):
    __tablename__ = "migration_user_review_queue"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_uid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    candidates_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class VerificationResultRecord(Base):
    __tablename__ = "migration_verification_results"

    result_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("migration_runs.run_id"), nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    run: Mapped[RunRecord] = relationship(back_populates="verification_results")
