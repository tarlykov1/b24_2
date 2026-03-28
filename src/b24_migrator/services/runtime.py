from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from b24_migrator.config import RuntimeConfig, load_runtime_config
from b24_migrator.domain.models import AuditEntry, Checkpoint, Job, LogEntry, Plan, Run
from b24_migrator.errors import AppError
from b24_migrator.services.executor import ExecutionService
from b24_migrator.services.planner import PlannerService
from b24_migrator.services.verifier import VerificationService
from b24_migrator.storage.base import Base
from b24_migrator.storage.repositories import (
    AuditRepository,
    CheckpointRepository,
    JobRepository,
    LogRepository,
    PlanRepository,
    RunRepository,
)
from b24_migrator.storage.session import SessionFactory


class RuntimeService:
    """Shared application layer used by CLI and Web API."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = load_runtime_config(config_path)
        try:
            self.session_factory = SessionFactory(self.config.database_url)
        except SQLAlchemyError as exc:
            raise AppError(
                code="RUNTIME_INIT_DB_ERROR",
                message="Failed to initialize runtime database engine",
                details={"error": str(exc)},
            ) from exc
        self.planner = PlannerService()
        self.executor = ExecutionService()
        self.verifier = VerificationService()

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self.session_factory.engine)

    def validate_deployment(self) -> dict[str, Any]:
        with self.session_factory.engine.connect():
            pass
        return {
            "config_path": str(self.config_path),
            "database": safe_database_details(self.config.database_url),
            "status": "ok",
        }

    def create_job(self, actor: str = "system") -> Job:
        job = Job(
            job_id=str(uuid4()),
            source_portal=self.config.source.base_url,
            target_portal=self.config.target.base_url,
            created_at=datetime.now(tz=timezone.utc),
        )
        with self.session_factory.create_session() as session:
            JobRepository(session).save(job)
            self._audit(session, actor, "create_job", {"job_id": job.job_id}, "success", {"job": to_dict(job)})
            session.commit()
        return job

    def create_plan(self, job_id: str | None = None, scope: list[str] | None = None, actor: str = "system") -> dict[str, Any]:
        final_scope = scope or self.config.default_scope
        with self.session_factory.create_session() as session:
            job_repo = JobRepository(session)
            plan_repo = PlanRepository(session)
            job = job_repo.get(job_id) if job_id else None
            created_job = False
            if job is None:
                job = Job(
                    job_id=str(uuid4()),
                    source_portal=self.config.source.base_url,
                    target_portal=self.config.target.base_url,
                    created_at=datetime.now(tz=timezone.utc),
                )
                job_repo.save(job)
                created_job = True

            plan = self.planner.create_plan(
                source_portal=job.source_portal,
                target_portal=job.target_portal,
                scope=final_scope,
                job_id=job.job_id,
            )
            plan_repo.save(plan)
            self._audit(
                session,
                actor,
                "create_plan",
                {"job_id": job.job_id, "scope": final_scope},
                "success",
                {"plan_id": plan.plan_id, "created_job": created_job},
            )
            session.commit()
        payload: dict[str, Any] = {"plan": plan}
        if created_job:
            payload["job"] = job
        return payload

    def get_status(self, *, job_id: str | None = None, plan_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        if not job_id and not plan_id and not run_id:
            raise AppError(
                code="VALIDATION_MISSING_IDENTIFIER",
                message="Provide at least one of --job-id, --plan-id, or --run-id",
            )
        with self.session_factory.create_session() as session:
            job_repo = JobRepository(session)
            plan_repo = PlanRepository(session)
            run_repo = RunRepository(session)
            if run_id:
                run = run_repo.get(run_id)
                if run is None:
                    raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
                return {"run": run}
            if plan_id:
                plan = plan_repo.get(plan_id)
                if plan is None:
                    raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": plan_id})
                latest = run_repo.find_latest_for_plan(plan_id)
                payload: dict[str, Any] = {"plan": plan}
                if latest is not None:
                    payload["latest_run"] = latest
                return payload
            assert job_id is not None
            job = job_repo.get(job_id)
            if job is None:
                raise AppError("JOB_NOT_FOUND", "Migration job does not exist", {"job_id": job_id})
            plans = plan_repo.list_for_job(job_id)
            return {"job": job, "plans": plans}

    def execute_plan(self, *, plan_id: str, dry_run: bool = False, actor: str = "system") -> Run:
        with self.session_factory.create_session() as session:
            plan = PlanRepository(session).get(plan_id)
            if plan is None:
                raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": plan_id})
            result = self.executor.execute(plan=plan, dry_run=dry_run)
            self._persist_run_result(session, result, "Plan executed")
            self._audit(
                session,
                actor,
                "execute_plan",
                {"plan_id": plan_id, "dry_run": dry_run},
                "success",
                {"run_id": result.run_id, "status": result.status},
            )
            session.commit()
        return result

    def resume_run(self, *, run_id: str | None = None, plan_id: str | None = None, actor: str = "system") -> Run:
        if not run_id and not plan_id:
            raise AppError("VALIDATION_MISSING_IDENTIFIER", "Either run_id or plan_id must be provided")
        with self.session_factory.create_session() as session:
            plan_repo = PlanRepository(session)
            run_repo = RunRepository(session)
            latest = run_repo.get(run_id) if run_id else run_repo.find_latest_for_plan(plan_id or "")
            if latest is None:
                raise AppError("RUN_NOT_FOUND", "No execution to resume", {"plan_id": plan_id, "run_id": run_id})
            plan = plan_repo.get(latest.plan_id)
            if plan is None:
                raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": latest.plan_id})
            resumed = self.executor.execute(plan=plan, dry_run=False, resume_from=latest)
            self._persist_run_result(session, resumed, "Run resumed from checkpoint")
            self._audit(
                session,
                actor,
                "resume_run",
                {"plan_id": plan_id, "run_id": run_id},
                "success",
                {"resumed_run_id": resumed.run_id, "status": resumed.status},
            )
            session.commit()
        return resumed

    def get_report(self, *, run_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            run_repo = RunRepository(session)
            log_repo = LogRepository(session)
            run: Run | None = None
            if run_id:
                run = run_repo.get(run_id)
            elif job_id:
                plans = PlanRepository(session).list_for_job(job_id)
                for plan in plans:
                    run = run_repo.find_latest_for_plan(plan.plan_id)
                    if run:
                        break
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id, "job_id": job_id})
            report = self.verifier.verify_run(run)
            logs = log_repo.list_for_run(run.run_id)
            return {"verification": report, "run": run, "logs": logs}

    def get_checkpoint(self, *, run_id: str) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            run = RunRepository(session).get(run_id)
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
            checkpoint = CheckpointRepository(session).latest_for_run(run_id)
            return {
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "status": run.status,
                "checkpoint_token": checkpoint.checkpoint_token if checkpoint else run.checkpoint_token,
                "processed_items": run.processed_items,
            }

    def list_logs(self, *, run_id: str, level: str | None = None) -> list[LogEntry]:
        with self.session_factory.create_session() as session:
            run = RunRepository(session).get(run_id)
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
            return LogRepository(session).list_for_run(run_id, level=level)

    def list_jobs(self, limit: int = 50) -> list[Job]:
        with self.session_factory.create_session() as session:
            return JobRepository(session).list_recent(limit=limit)

    def list_plans(self, limit: int = 50) -> list[Plan]:
        with self.session_factory.create_session() as session:
            return PlanRepository(session).list_recent(limit=limit)

    def list_runs(self, limit: int = 50, status: str | None = None) -> list[Run]:
        with self.session_factory.create_session() as session:
            return RunRepository(session).list_recent(limit=limit, status=status)

    def list_audit(self, limit: int = 200) -> list[AuditEntry]:
        with self.session_factory.create_session() as session:
            return AuditRepository(session).list_recent(limit=limit)

    def _persist_run_result(self, session: Any, result: Run, log_message: str) -> None:
        RunRepository(session).save(result)
        if result.checkpoint_token:
            CheckpointRepository(session).save(
                Checkpoint(
                    checkpoint_id=None,
                    run_id=result.run_id,
                    checkpoint_token=result.checkpoint_token,
                    state={"processed_items": result.processed_items, "status": result.status},
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
        LogRepository(session).save(
            LogEntry(
                log_id=None,
                run_id=result.run_id,
                level="INFO",
                message=log_message,
                created_at=datetime.now(tz=timezone.utc),
            )
        )

    def _audit(
        self,
        session: Any,
        actor: str,
        action: str,
        input_payload: dict[str, Any],
        outcome: str,
        details: dict[str, Any] | None,
    ) -> None:
        AuditRepository(session).save(
            AuditEntry(
                audit_id=None,
                actor=actor,
                action=action,
                input_payload=input_payload,
                outcome=outcome,
                details=details,
                created_at=datetime.now(tz=timezone.utc),
            )
        )


def to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return value.__dict__.copy()


def safe_database_details(database_url: str) -> dict[str, Any]:
    parsed = make_url(database_url)
    return {
        "driver": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username,
        "dsn": parsed.render_as_string(hide_password=True),
    }


def save_config(config_path: Path, config: RuntimeConfig) -> None:
    import yaml

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config.model_dump(mode="python"), fh, allow_unicode=True, sort_keys=False)
