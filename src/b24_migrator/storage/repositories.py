from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from b24_migrator.domain.models import ExecutionResult, MigrationPlan
from b24_migrator.storage.models import PlanRecord, RunRecord


class PlanRepository:
    """Persistence layer for migration plans."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, plan: MigrationPlan) -> None:
        self._session.merge(
            PlanRecord(
                plan_id=plan.plan_id,
                source_portal=plan.source_portal,
                target_portal=plan.target_portal,
                scope_csv=",".join(plan.scope),
                deterministic_hash=plan.deterministic_hash,
                created_at=plan.created_at,
            )
        )

    def get(self, plan_id: str) -> MigrationPlan | None:
        record = self._session.get(PlanRecord, plan_id)
        if record is None:
            return None
        return MigrationPlan(
            plan_id=record.plan_id,
            source_portal=record.source_portal,
            target_portal=record.target_portal,
            scope=record.scope_csv.split(",") if record.scope_csv else [],
            deterministic_hash=record.deterministic_hash,
            created_at=record.created_at,
        )


class RunRepository:
    """Persistence layer for migration executions/checkpoints."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, result: ExecutionResult) -> None:
        self._session.merge(
            RunRecord(
                run_id=result.run_id,
                plan_id=result.plan_id,
                status=result.status,
                processed_items=result.processed_items,
                checkpoint_token=result.checkpoint_token,
                updated_at=datetime.now(tz=timezone.utc),
            )
        )

    def get(self, run_id: str) -> ExecutionResult | None:
        record = self._session.get(RunRecord, run_id)
        if record is None:
            return None
        return ExecutionResult(
            plan_id=record.plan_id,
            run_id=record.run_id,
            status=record.status,
            processed_items=record.processed_items,
            checkpoint_token=record.checkpoint_token,
        )

    def find_latest_for_plan(self, plan_id: str) -> ExecutionResult | None:
        stmt = (
            select(RunRecord)
            .where(RunRecord.plan_id == plan_id)
            .order_by(RunRecord.updated_at.desc())
            .limit(1)
        )
        record = self._session.execute(stmt).scalar_one_or_none()
        if record is None:
            return None
        return ExecutionResult(
            plan_id=record.plan_id,
            run_id=record.run_id,
            status=record.status,
            processed_items=record.processed_items,
            checkpoint_token=record.checkpoint_token,
        )
