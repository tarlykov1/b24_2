from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from b24_migrator.storage.base import Base


class PlanRecord(Base):
    __tablename__ = "migration_plans"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_portal: Mapped[str] = mapped_column(String(255), nullable=False)
    target_portal: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_csv: Mapped[str] = mapped_column(Text, nullable=False)
    deterministic_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunRecord(Base):
    __tablename__ = "migration_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    processed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
