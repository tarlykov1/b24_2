from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from b24_migrator.domain.models import Checkpoint, Job, LogEntry, Plan, Run
from b24_migrator.storage.models import CheckpointRecord, JobRecord, LogRecord, PlanRecord, RunRecord


class JobRepository:
    """Persistence layer for jobs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, job: Job) -> None:
        self._session.merge(
            JobRecord(
                job_id=job.job_id,
                source_portal=job.source_portal,
                target_portal=job.target_portal,
                created_at=job.created_at,
            )
        )

    def get(self, job_id: str) -> Job | None:
        record = self._session.get(JobRecord, job_id)
        if record is None:
            return None
        return Job(
            job_id=record.job_id,
            source_portal=record.source_portal,
            target_portal=record.target_portal,
            created_at=record.created_at,
        )


class PlanRepository:
    """Persistence layer for migration plans."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, plan: Plan) -> None:
        self._session.merge(
            PlanRecord(
                plan_id=plan.plan_id,
                job_id=plan.job_id,
                source_portal=plan.source_portal,
                target_portal=plan.target_portal,
                scope_csv=",".join(plan.scope),
                deterministic_hash=plan.deterministic_hash,
                created_at=plan.created_at,
            )
        )

    def get(self, plan_id: str) -> Plan | None:
        record = self._session.get(PlanRecord, plan_id)
        if record is None:
            return None
        return Plan(
            plan_id=record.plan_id,
            job_id=record.job_id,
            source_portal=record.source_portal,
            target_portal=record.target_portal,
            scope=record.scope_csv.split(",") if record.scope_csv else [],
            deterministic_hash=record.deterministic_hash,
            created_at=record.created_at,
        )

    def list_for_job(self, job_id: str) -> list[Plan]:
        stmt = select(PlanRecord).where(PlanRecord.job_id == job_id).order_by(PlanRecord.created_at.desc())
        rows = self._session.execute(stmt).scalars().all()
        return [
            Plan(
                plan_id=row.plan_id,
                job_id=row.job_id,
                source_portal=row.source_portal,
                target_portal=row.target_portal,
                scope=row.scope_csv.split(",") if row.scope_csv else [],
                deterministic_hash=row.deterministic_hash,
                created_at=row.created_at,
            )
            for row in rows
        ]


class RunRepository:
    """Persistence layer for migration executions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, result: Run) -> None:
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

    def get(self, run_id: str) -> Run | None:
        record = self._session.get(RunRecord, run_id)
        if record is None:
            return None
        return Run(
            plan_id=record.plan_id,
            run_id=record.run_id,
            status=record.status,
            processed_items=record.processed_items,
            checkpoint_token=record.checkpoint_token,
        )

    def find_latest_for_plan(self, plan_id: str) -> Run | None:
        stmt = (
            select(RunRecord)
            .where(RunRecord.plan_id == plan_id)
            .order_by(RunRecord.updated_at.desc())
            .limit(1)
        )
        record = self._session.execute(stmt).scalar_one_or_none()
        if record is None:
            return None
        return Run(
            plan_id=record.plan_id,
            run_id=record.run_id,
            status=record.status,
            processed_items=record.processed_items,
            checkpoint_token=record.checkpoint_token,
        )


class CheckpointRepository:
    """Persistence layer for run checkpoints."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, checkpoint: Checkpoint) -> None:
        self._session.add(
            CheckpointRecord(
                run_id=checkpoint.run_id,
                checkpoint_token=checkpoint.checkpoint_token,
                state_json=json.dumps(checkpoint.state, sort_keys=True) if checkpoint.state is not None else None,
                created_at=checkpoint.created_at,
            )
        )

    def latest_for_run(self, run_id: str) -> Checkpoint | None:
        stmt = (
            select(CheckpointRecord)
            .where(CheckpointRecord.run_id == run_id)
            .order_by(CheckpointRecord.created_at.desc(), CheckpointRecord.checkpoint_id.desc())
            .limit(1)
        )
        record = self._session.execute(stmt).scalar_one_or_none()
        if record is None:
            return None
        return Checkpoint(
            checkpoint_id=record.checkpoint_id,
            run_id=record.run_id,
            checkpoint_token=record.checkpoint_token,
            state=json.loads(record.state_json) if record.state_json else None,
            created_at=record.created_at,
        )


class LogRepository:
    """Persistence layer for run logs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, log_entry: LogEntry) -> None:
        self._session.add(
            LogRecord(
                run_id=log_entry.run_id,
                level=log_entry.level,
                message=log_entry.message,
                created_at=log_entry.created_at,
            )
        )

    def list_for_run(self, run_id: str) -> list[LogEntry]:
        stmt = select(LogRecord).where(LogRecord.run_id == run_id).order_by(LogRecord.created_at.asc(), LogRecord.log_id.asc())
        records = self._session.execute(stmt).scalars().all()
        return [
            LogEntry(
                log_id=row.log_id,
                run_id=row.run_id,
                level=row.level,
                message=row.message,
                created_at=row.created_at,
            )
            for row in records
        ]
