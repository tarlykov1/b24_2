from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from b24_migrator.domain.models import AuditEntry, Checkpoint, Job, LogEntry, MappingRecord, Plan, Run, UserReviewItem, VerificationResult
from b24_migrator.storage.models import (
    AuditRecord,
    CheckpointRecord,
    JobRecord,
    LogRecord,
    MappingRecordModel,
    PlanRecord,
    RunRecord,
    UserReviewQueueRecord,
    VerificationResultRecord,
)


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

    def list_recent(self, limit: int = 20) -> list[Job]:
        stmt = select(JobRecord).order_by(JobRecord.created_at.desc()).limit(limit)
        rows = self._session.execute(stmt).scalars().all()
        return [
            Job(
                job_id=row.job_id,
                source_portal=row.source_portal,
                target_portal=row.target_portal,
                created_at=row.created_at,
            )
            for row in rows
        ]


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

    def list_recent(self, limit: int = 50) -> list[Plan]:
        stmt = select(PlanRecord).order_by(PlanRecord.created_at.desc()).limit(limit)
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
        stmt = select(RunRecord).where(RunRecord.plan_id == plan_id).order_by(RunRecord.updated_at.desc()).limit(1)
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

    def list_recent(self, limit: int = 50, status: str | None = None) -> list[Run]:
        stmt = select(RunRecord)
        if status:
            stmt = stmt.where(RunRecord.status == status)
        stmt = stmt.order_by(RunRecord.updated_at.desc()).limit(limit)
        rows = self._session.execute(stmt).scalars().all()
        return [
            Run(
                plan_id=row.plan_id,
                run_id=row.run_id,
                status=row.status,
                processed_items=row.processed_items,
                checkpoint_token=row.checkpoint_token,
            )
            for row in rows
        ]


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

    def list_for_run(self, run_id: str, level: str | None = None) -> list[LogEntry]:
        stmt = select(LogRecord).where(LogRecord.run_id == run_id)
        if level:
            stmt = stmt.where(LogRecord.level == level)
        stmt = stmt.order_by(LogRecord.created_at.asc(), LogRecord.log_id.asc())
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


class AuditRepository:
    """Persistence layer for user action audit."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, entry: AuditEntry) -> None:
        self._session.add(
            AuditRecord(
                actor=entry.actor,
                action=entry.action,
                input_payload_json=json.dumps(entry.input_payload, sort_keys=True, default=str),
                outcome=entry.outcome,
                details_json=json.dumps(entry.details, sort_keys=True, default=str) if entry.details is not None else None,
                created_at=entry.created_at,
            )
        )

    def list_recent(self, limit: int = 200) -> list[AuditEntry]:
        stmt = select(AuditRecord).order_by(AuditRecord.created_at.desc(), AuditRecord.audit_id.desc()).limit(limit)
        rows = self._session.execute(stmt).scalars().all()
        return [
            AuditEntry(
                audit_id=row.audit_id,
                actor=row.actor,
                action=row.action,
                input_payload=json.loads(row.input_payload_json),
                outcome=row.outcome,
                details=json.loads(row.details_json) if row.details_json else None,
                created_at=row.created_at,
            )
            for row in rows
        ]


class MappingRepository:
    """Persistence layer for canonical source-target mapping rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, mapping: MappingRecord) -> None:
        existing = self._session.execute(
            select(MappingRecordModel).where(
                MappingRecordModel.entity_type == mapping.entity_type,
                MappingRecordModel.source_id == mapping.source_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            self._session.add(
                MappingRecordModel(
                    entity_type=mapping.entity_type,
                    source_id=mapping.source_id,
                    source_uid=mapping.source_uid,
                    target_id=mapping.target_id,
                    target_uid=mapping.target_uid,
                    status=mapping.status,
                    resolution_strategy=mapping.resolution_strategy,
                    verification_status=mapping.verification_status,
                    linked_parent_type=mapping.linked_parent_type,
                    linked_parent_source_id=mapping.linked_parent_source_id,
                    linked_parent_target_id=mapping.linked_parent_target_id,
                    payload_hash=mapping.payload_hash,
                    error_payload_json=json.dumps(mapping.error_payload, sort_keys=True) if mapping.error_payload else None,
                    created_at=mapping.created_at,
                    updated_at=mapping.updated_at,
                )
            )
            return
        existing.source_uid = mapping.source_uid
        existing.target_id = mapping.target_id
        existing.target_uid = mapping.target_uid
        existing.status = mapping.status
        existing.resolution_strategy = mapping.resolution_strategy
        existing.verification_status = mapping.verification_status
        existing.linked_parent_type = mapping.linked_parent_type
        existing.linked_parent_source_id = mapping.linked_parent_source_id
        existing.linked_parent_target_id = mapping.linked_parent_target_id
        existing.payload_hash = mapping.payload_hash
        existing.error_payload_json = json.dumps(mapping.error_payload, sort_keys=True) if mapping.error_payload else None
        existing.updated_at = mapping.updated_at

    def list_all(self, entity_type: str | None = None, status: str | None = None, limit: int = 1000) -> list[MappingRecord]:
        stmt = select(MappingRecordModel)
        if entity_type:
            stmt = stmt.where(MappingRecordModel.entity_type == entity_type)
        if status:
            stmt = stmt.where(MappingRecordModel.status == status)
        stmt = stmt.order_by(MappingRecordModel.updated_at.desc(), MappingRecordModel.mapping_id.desc()).limit(limit)
        rows = self._session.execute(stmt).scalars().all()
        return [self._to_domain(row) for row in rows]

    def get(self, entity_type: str, source_id: str) -> MappingRecord | None:
        row = self._session.execute(
            select(MappingRecordModel).where(
                MappingRecordModel.entity_type == entity_type,
                MappingRecordModel.source_id == source_id,
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row else None

    @staticmethod
    def _to_domain(row: MappingRecordModel) -> MappingRecord:
        return MappingRecord(
            mapping_id=row.mapping_id,
            entity_type=row.entity_type,
            source_id=row.source_id,
            source_uid=row.source_uid,
            target_id=row.target_id,
            target_uid=row.target_uid,
            status=row.status,
            resolution_strategy=row.resolution_strategy,
            verification_status=row.verification_status,
            linked_parent_type=row.linked_parent_type,
            linked_parent_source_id=row.linked_parent_source_id,
            linked_parent_target_id=row.linked_parent_target_id,
            payload_hash=row.payload_hash,
            error_payload=json.loads(row.error_payload_json) if row.error_payload_json else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class UserReviewQueueRepository:
    """Persistence for user match ambiguities/manual review queue."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, item: UserReviewItem) -> None:
        if item.review_id is not None:
            row = self._session.get(UserReviewQueueRecord, item.review_id)
            if row is not None:
                row.source_id = item.source_id
                row.source_uid = item.source_uid
                row.candidates_json = json.dumps(item.candidates, sort_keys=True)
                row.reason = item.reason
                row.status = item.status
                row.updated_at = item.updated_at
                return
        self._session.add(
            UserReviewQueueRecord(
                source_id=item.source_id,
                source_uid=item.source_uid,
                candidates_json=json.dumps(item.candidates, sort_keys=True),
                reason=item.reason,
                status=item.status,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )

    def list_open(self, limit: int = 500) -> list[UserReviewItem]:
        rows = self._session.execute(
            select(UserReviewQueueRecord)
            .where(UserReviewQueueRecord.status == "open")
            .order_by(UserReviewQueueRecord.created_at.asc(), UserReviewQueueRecord.review_id.asc())
            .limit(limit)
        ).scalars().all()
        return [self._to_domain(row) for row in rows]

    def close_open_by_source(self, source_id: str) -> None:
        rows = self._session.execute(
            select(UserReviewQueueRecord).where(
                UserReviewQueueRecord.source_id == source_id,
                UserReviewQueueRecord.status == "open",
            )
        ).scalars().all()
        now = datetime.now(tz=timezone.utc)
        for row in rows:
            row.status = "resolved"
            row.updated_at = now

    @staticmethod
    def _to_domain(row: UserReviewQueueRecord) -> UserReviewItem:
        return UserReviewItem(
            review_id=row.review_id,
            source_id=row.source_id,
            source_uid=row.source_uid,
            candidates=json.loads(row.candidates_json),
            reason=row.reason,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class VerificationResultRepository:
    """Persistence for verification check output."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_many(self, rows: list[VerificationResult]) -> None:
        for row in rows:
            self._session.add(
                VerificationResultRecord(
                    run_id=row.run_id,
                    check_type=row.check_type,
                    entity_type=row.entity_type,
                    status=row.status,
                    details_json=json.dumps(row.details, sort_keys=True, default=str),
                    created_at=row.created_at,
                )
            )

    def list_for_run(self, run_id: str) -> list[VerificationResult]:
        rows = self._session.execute(
            select(VerificationResultRecord)
            .where(VerificationResultRecord.run_id == run_id)
            .order_by(VerificationResultRecord.created_at.asc(), VerificationResultRecord.result_id.asc())
        ).scalars().all()
        return [
            VerificationResult(
                result_id=row.result_id,
                run_id=row.run_id,
                check_type=row.check_type,
                entity_type=row.entity_type,
                status=row.status,
                details=json.loads(row.details_json),
                created_at=row.created_at,
            )
            for row in rows
        ]
