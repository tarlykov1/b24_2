from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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
