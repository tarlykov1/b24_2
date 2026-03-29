from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from b24_migrator.config import RuntimeConfig, load_runtime_config
from b24_migrator.domain.models import AuditEntry, Checkpoint, Job, LogEntry, MappingRecord, Plan, Run
from b24_migrator.errors import AppError
from b24_migrator.services.cutover import CutoverService
from b24_migrator.services.data_plane import DataPlaneMigrationService
from b24_migrator.services.domains import DomainRegistryService
from b24_migrator.services.executor import ExecutionService
from b24_migrator.services.mapping import MappingService, UserResolutionService
from b24_migrator.services.matrix import MigrationMatrixService
from b24_migrator.services.planner import PlannerService
from b24_migrator.services.verifier import VerificationService
from b24_migrator.storage.base import Base
from b24_migrator.storage.repositories import (
    AuditRepository,
    CheckpointRepository,
    JobRepository,
    LogRepository,
    MappingRepository,
    PlanRepository,
    RunRepository,
    UserReviewQueueRepository,
    VerificationResultRepository,
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
        self.matrix = MigrationMatrixService()
        self.mapping = MappingService()
        self.user_resolution = UserResolutionService()
        self.domain_registry = DomainRegistryService()
        self.cutover = CutoverService()
        self.data_plane = DataPlaneMigrationService()

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
            mappings = MappingRepository(session).list_all(limit=5000)
            report = self.verifier.verify_run(run, mappings)
            verification_rows = self.verifier.build_results(run, mappings)
            VerificationResultRepository(session).save_many(verification_rows)
            logs = log_repo.list_for_run(run.run_id)
            session.commit()
            return {
                "verification": report,
                "verification_results": VerificationResultRepository(session).list_for_run(run.run_id),
                "run": run,
                "logs": logs,
            }

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

    def list_matrix(self) -> list[dict[str, Any]]:
        return [to_dict(i) for i in self.matrix.list_entries()]

    def list_domain_modules(self) -> list[dict[str, Any]]:
        return [to_dict(i) for i in self.domain_registry.list_domains()]

    def get_dependency_graph(self) -> list[dict[str, Any]]:
        return [to_dict(i) for i in self.domain_registry.execution_graph()]

    def upsert_mapping(self, actor: str = "system", **kwargs: Any) -> MappingRecord:
        with self.session_factory.create_session() as session:
            mapping = self.mapping.upsert_mapping(session, **kwargs)
            self._audit(session, actor, "upsert_mapping", kwargs, "success", {"mapping": to_dict(mapping)})
            session.commit()
            return mapping

    def list_mappings(self, entity_type: str | None = None, status: str | None = None, limit: int = 1000) -> list[MappingRecord]:
        with self.session_factory.create_session() as session:
            return MappingRepository(session).list_all(entity_type=entity_type, status=status, limit=limit)

    def resolve_user_mapping(self, source_user: dict[str, Any], target_candidates: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            resolved = self.user_resolution.resolve_user(session, source_user=source_user, target_candidates=target_candidates)
            details = to_dict(resolved)
            self._audit(session, actor, "resolve_user_mapping", {"source_user": source_user}, "success", details)
            session.commit()
            return details

    def users_discover(self, source_users: list[dict[str, Any]], target_users: list[dict[str, Any]]) -> dict[str, Any]:
        return {"source_count": len(source_users), "target_count": len(target_users)}

    def users_map(self, source_users: list[dict[str, Any]], target_users: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.sync_users(session, source_users=source_users, target_users=target_users)
            self._audit(session, actor, "users_map", {"source_count": len(source_users), "target_count": len(target_users)}, "success", result)
            session.commit()
            return result

    def users_review(self, source_id: str, target_id: str, target_uid: str | None = None, actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            mapping = self.data_plane.user_review(session, source_id=source_id, target_id=target_id, target_uid=target_uid, actor=actor)
            payload = to_dict(mapping)
            self._audit(session, actor, "users_review", {"source_id": source_id, "target_id": target_id}, "success", payload)
            session.commit()
            return payload

    def groups_sync(self, source_groups: list[dict[str, Any]], target_groups: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            user_map = {m.source_id: m.target_id for m in MappingRepository(session).list_all(entity_type="users", status="resolved", limit=50000) if m.target_id}
            result = self.data_plane.sync_groups_or_projects(
                session,
                entity_type="groups",
                source_entities=source_groups,
                target_entities=target_groups,
                user_map=user_map,
            )
            self._audit(session, actor, "groups_sync", {"source_count": len(source_groups)}, "success", result)
            session.commit()
            return result

    def projects_sync(self, source_projects: list[dict[str, Any]], target_projects: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            user_map = {m.source_id: m.target_id for m in MappingRepository(session).list_all(entity_type="users", status="resolved", limit=50000) if m.target_id}
            result = self.data_plane.sync_groups_or_projects(
                session,
                entity_type="projects",
                source_entities=source_projects,
                target_entities=target_projects,
                user_map=user_map,
            )
            self._audit(session, actor, "projects_sync", {"source_count": len(source_projects)}, "success", result)
            session.commit()
            return result

    def tasks_migrate(self, source_tasks: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_tasks(session, source_tasks=source_tasks)
            self._audit(session, actor, "tasks_migrate", {"source_count": len(source_tasks)}, "success", result)
            session.commit()
            return result

    def comments_migrate(self, source_comments: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_comments(session, source_comments=source_comments)
            self._audit(session, actor, "comments_migrate", {"source_count": len(source_comments)}, "success", result)
            session.commit()
            return result

    def file_refs_migrate(self, source_refs: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_file_refs(session, source_refs=source_refs)
            self._audit(session, actor, "file_refs_migrate", {"source_count": len(source_refs)}, "success", result)
            session.commit()
            return result

    def crm_sync(
        self,
        source_categories: list[dict[str, Any]],
        target_categories: list[dict[str, Any]],
        source_stages: list[dict[str, Any]],
        target_stages: list[dict[str, Any]],
        source_custom_fields: list[dict[str, Any]],
        target_custom_fields: list[dict[str, Any]],
        actor: str = "system",
    ) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.sync_crm_dictionaries(
                session,
                source_categories=source_categories,
                target_categories=target_categories,
                source_stages=source_stages,
                target_stages=target_stages,
                source_custom_fields=source_custom_fields,
                target_custom_fields=target_custom_fields,
            )
            self._audit(
                session,
                actor,
                "crm_sync",
                {"categories": len(source_categories), "stages": len(source_stages), "custom_fields": len(source_custom_fields)},
                "success",
                result,
            )
            session.commit()
            return result

    def crm_contacts_migrate(
        self,
        source_contacts: list[dict[str, Any]],
        target_contacts: list[dict[str, Any]],
        actor: str = "system",
    ) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_crm_contacts(session, source_contacts=source_contacts, target_contacts=target_contacts)
            self._audit(session, actor, "crm_contacts_migrate", {"source_count": len(source_contacts)}, "success", result)
            session.commit()
            return result

    def crm_companies_migrate(
        self,
        source_companies: list[dict[str, Any]],
        target_companies: list[dict[str, Any]],
        actor: str = "system",
    ) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_crm_companies(session, source_companies=source_companies, target_companies=target_companies)
            self._audit(session, actor, "crm_companies_migrate", {"source_count": len(source_companies)}, "success", result)
            session.commit()
            return result

    def crm_deals_migrate(
        self,
        source_deals: list[dict[str, Any]],
        target_deals: list[dict[str, Any]],
        actor: str = "system",
    ) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_crm_deals(session, source_deals=source_deals, target_deals=target_deals)
            self._audit(session, actor, "crm_deals_migrate", {"source_count": len(source_deals)}, "success", result)
            session.commit()
            return result

    def crm_comments_migrate(self, source_comments: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_crm_comments(session, source_comments=source_comments)
            self._audit(session, actor, "crm_comments_migrate", {"source_count": len(source_comments)}, "success", result)
            session.commit()
            return result

    def crm_file_refs_migrate(self, source_refs: list[dict[str, Any]], actor: str = "system") -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            result = self.data_plane.migrate_crm_file_refs(session, source_refs=source_refs)
            self._audit(session, actor, "crm_file_refs_migrate", {"source_count": len(source_refs)}, "success", result)
            session.commit()
            return result

    def list_user_review_queue(self, limit: int = 500) -> list[dict[str, Any]]:
        with self.session_factory.create_session() as session:
            return [to_dict(i) for i in UserReviewQueueRepository(session).list_open(limit=limit)]

    def verification_results(self, run_id: str) -> list[dict[str, Any]]:
        with self.session_factory.create_session() as session:
            return [to_dict(r) for r in VerificationResultRepository(session).list_for_run(run_id)]

    def target_inspection(self) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            mappings = MappingRepository(session).list_all(limit=5000)
            return self.cutover.target_inspection(mappings)

    def cleanup_plan(self, dry_run: bool = True) -> dict[str, Any]:
        with self.session_factory.create_session() as session:
            mappings = MappingRepository(session).list_all(limit=5000)
            return self.cutover.cleanup_plan(mappings, dry_run=dry_run)

    def cleanup_execute(self, dry_run: bool = True) -> dict[str, Any]:
        plan = self.cleanup_plan(dry_run=True)
        return self.cutover.cleanup_execute(plan, dry_run=dry_run)

    def delta_plan(self) -> dict[str, Any]:
        return self.cutover.delta_plan(self.domain_registry.execution_graph())

    def delta_execute(self, plan_id: str) -> dict[str, Any]:
        return self.cutover.delta_execute(plan_id)

    def cutover_readiness(self, run_id: str) -> dict[str, Any]:
        inspection = self.target_inspection()
        verification = self.get_report(run_id=run_id)["verification"]
        return self.cutover.cutover_readiness(inspection, verification)

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
    raise TypeError(f"Unsupported audit payload type: {type(value)!r}")


def safe_database_details(database_url: str) -> dict[str, Any]:
    parsed = make_url(database_url)
    dsn_password = "***" if parsed.password else ""
    auth = ""
    if parsed.username:
        auth = parsed.username
        if parsed.password is not None:
            auth = f"{auth}:{dsn_password}"
        auth = f"{auth}@"
    host = parsed.host or ""
    port = f":{parsed.port}" if parsed.port else ""
    dsn = f"{parsed.drivername}://{auth}{host}{port}/{parsed.database or ''}"
    return {
        "drivername": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username,
        "password": "***" if parsed.password else None,
        "dsn": dsn,
    }


def save_config(path: Path, config: RuntimeConfig) -> None:
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
