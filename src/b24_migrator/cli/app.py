from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from b24_migrator.cli.exit_codes import ExitCode
from b24_migrator.config import load_runtime_config
from b24_migrator.domain.models import Checkpoint, Job, LogEntry, Run
from b24_migrator.errors import AppError
from b24_migrator.schemas import JsonResponse
from b24_migrator.services.executor import ExecutionService
from b24_migrator.services.planner import PlannerService
from b24_migrator.services.verifier import VerificationService
from b24_migrator.storage.base import Base
from b24_migrator.storage.repositories import (
    CheckpointRepository,
    JobRepository,
    LogRepository,
    PlanRepository,
    RunRepository,
)
from b24_migrator.storage.session import SessionFactory

app = typer.Typer(help="Bitrix24 deterministic migration runtime")


class RuntimeContainer:
    """Factory-like container used by CLI handlers."""

    def __init__(self, config_path: Path) -> None:
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


def _emit(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _exit_code_for_error(exc: AppError) -> ExitCode:
    if exc.code.startswith("CONFIG_"):
        return ExitCode.CONFIG_ERROR
    if exc.code.startswith("VALIDATION_"):
        return ExitCode.VALIDATION_ERROR
    if exc.code.startswith("DB_"):
        return ExitCode.DATABASE_CONNECTION_ERROR
    return ExitCode.RUNTIME_FAILURE


def _handle_error(exc: AppError) -> None:
    _emit(exc.to_dict())
    raise typer.Exit(code=int(_exit_code_for_error(exc)))


def _handle_sqlalchemy_error(exc: SQLAlchemyError) -> None:
    _handle_error(
        AppError(
            code="DB_CONNECTION_ERROR",
            message="Unable to connect to the runtime database",
            details={"error": str(exc)},
        )
    )


def _asdict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)
    except (TypeError, ValueError):
        if hasattr(value, "__dict__"):
            return value.__dict__.copy()
        raise TypeError(f"Unsupported value for dict serialization: {type(value)!r}")


def _safe_database_details(database_url: str) -> dict[str, Any]:
    parsed = make_url(database_url)
    return {
        "driver": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username,
        "dsn": parsed.render_as_string(hide_password=True),
    }


def _new_job_from_config(container: RuntimeContainer) -> Job:
    return Job(
        job_id=str(uuid4()),
        source_portal=container.config.source.base_url,
        target_portal=container.config.target.base_url,
        created_at=datetime.now(tz=timezone.utc),
    )


@app.command("create-job")
def create_job_command(
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Create and persist top-level migration job."""

    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        job = _new_job_from_config(container)

        with container.session_factory.create_session() as session:
            repo = JobRepository(session)
            repo.save(job)
            session.commit()

        _emit(JsonResponse(ok=True, data={"job": _asdict(job)}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("plan")
def plan_command(
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
    job_id: str | None = typer.Option(None, "--job-id"),
    scope: list[str] = typer.Option([], "--scope", help="Repeatable scope override."),
) -> None:
    """Create deterministic plan for an existing (or newly created) job."""

    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        final_scope = scope or container.config.default_scope
        with container.session_factory.create_session() as session:
            job_repo = JobRepository(session)
            plan_repo = PlanRepository(session)

            job = job_repo.get(job_id) if job_id else None
            created_job = False
            if job is None:
                job = _new_job_from_config(container)
                job_repo.save(job)
                created_job = True

            plan = container.planner.create_plan(
                source_portal=job.source_portal,
                target_portal=job.target_portal,
                scope=final_scope,
                job_id=job.job_id,
            )
            plan_repo.save(plan)
            session.commit()

        payload: dict[str, Any] = {"plan": _asdict(plan)}
        if created_job:
            payload["job"] = _asdict(job)
        _emit(JsonResponse(ok=True, data=payload).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("status")
def status_command(
    job_id: str | None = typer.Option(None, "--job-id"),
    plan_id: str | None = typer.Option(None, "--plan-id"),
    run_id: str | None = typer.Option(None, "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Return current status of a migration job, plan, or run."""

    try:
        if not job_id and not plan_id and not run_id:
            raise AppError(
                code="VALIDATION_MISSING_IDENTIFIER",
                message="Provide at least one of --job-id, --plan-id, or --run-id",
            )
        container = RuntimeContainer(config)
        container.ensure_schema()
        with container.session_factory.create_session() as session:
            job_repo = JobRepository(session)
            plan_repo = PlanRepository(session)
            run_repo = RunRepository(session)

            if run_id:
                run = run_repo.get(run_id)
                if run is None:
                    raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
                _emit(JsonResponse(ok=True, data={"run": _asdict(run)}).to_dict())
                return

            if plan_id:
                plan = plan_repo.get(plan_id)
                if plan is None:
                    raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": plan_id})
                latest = run_repo.find_latest_for_plan(plan_id)
                payload: dict[str, Any] = {"plan": _asdict(plan)}
                if latest is not None:
                    payload["latest_run"] = _asdict(latest)
                _emit(JsonResponse(ok=True, data=payload).to_dict())
                return

            assert job_id is not None
            job = job_repo.get(job_id)
            if job is None:
                raise AppError("JOB_NOT_FOUND", "Migration job does not exist", {"job_id": job_id})
            plans = plan_repo.list_for_job(job_id)
            _emit(JsonResponse(ok=True, data={"job": _asdict(job), "plans": [_asdict(plan) for plan in plans]}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("execute")
def execute_command(
    plan_id: str = typer.Option(..., "--plan-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Execute migration plan with checkpoint/log persistence."""

    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        with container.session_factory.create_session() as session:
            plan_repo = PlanRepository(session)
            run_repo = RunRepository(session)
            checkpoint_repo = CheckpointRepository(session)
            log_repo = LogRepository(session)

            plan = plan_repo.get(plan_id)
            if plan is None:
                raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": plan_id})
            result = container.executor.execute(plan=plan, dry_run=dry_run)
            run_repo.save(result)
            if result.checkpoint_token:
                checkpoint_repo.save(
                    Checkpoint(
                        checkpoint_id=None,
                        run_id=result.run_id,
                        checkpoint_token=result.checkpoint_token,
                        state={"processed_items": result.processed_items, "status": result.status},
                        created_at=datetime.now(tz=timezone.utc),
                    )
                )
            log_repo.save(
                LogEntry(
                    log_id=None,
                    run_id=result.run_id,
                    level="INFO",
                    message="Plan executed",
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            session.commit()

        _emit(JsonResponse(ok=True, data={"run": _asdict(result)}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("resume")
def resume_command(
    plan_id: str | None = typer.Option(None, "--plan-id"),
    run_id: str | None = typer.Option(None, "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Resume execution from latest stored checkpoint by run or plan."""

    try:
        if not plan_id and not run_id:
            raise AppError(
                code="VALIDATION_MISSING_IDENTIFIER",
                message="Either --plan-id or --run-id must be provided",
            )
        container = RuntimeContainer(config)
        container.ensure_schema()
        with container.session_factory.create_session() as session:
            plan_repo = PlanRepository(session)
            run_repo = RunRepository(session)
            checkpoint_repo = CheckpointRepository(session)
            log_repo = LogRepository(session)

            latest: Run | None = run_repo.get(run_id) if run_id else run_repo.find_latest_for_plan(plan_id or "")
            if latest is None:
                raise AppError("RUN_NOT_FOUND", "No execution to resume", {"plan_id": plan_id, "run_id": run_id})
            plan = plan_repo.get(latest.plan_id)
            if plan is None:
                raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": latest.plan_id})
            resumed = container.executor.execute(plan=plan, dry_run=False, resume_from=latest)
            run_repo.save(resumed)
            if resumed.checkpoint_token:
                checkpoint_repo.save(
                    Checkpoint(
                        checkpoint_id=None,
                        run_id=resumed.run_id,
                        checkpoint_token=resumed.checkpoint_token,
                        state={"processed_items": resumed.processed_items, "status": resumed.status},
                        created_at=datetime.now(tz=timezone.utc),
                    )
                )
            log_repo.save(
                LogEntry(
                    log_id=None,
                    run_id=resumed.run_id,
                    level="INFO",
                    message="Run resumed from checkpoint",
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            session.commit()

        _emit(JsonResponse(ok=True, data={"run": _asdict(resumed)}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("report")
def report_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Return verification report for a stored run and related logs."""

    try:
        container = RuntimeContainer(config)
        with container.session_factory.create_session() as session:
            run_repo = RunRepository(session)
            log_repo = LogRepository(session)
            run = run_repo.get(run_id)
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
            report = container.verifier.verify_run(run)
            logs = log_repo.list_for_run(run_id)

        _emit(
            JsonResponse(
                ok=True,
                data={"verification": report, "run": _asdict(run), "logs": [_asdict(entry) for entry in logs]},
            ).to_dict()
        )
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("verify")
def verify_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Backward-compatible alias for report."""

    report_command(run_id=run_id, config=config)


@app.command("checkpoint")
def checkpoint_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Return latest persisted checkpoint info for a run."""

    try:
        container = RuntimeContainer(config)
        with container.session_factory.create_session() as session:
            run_repo = RunRepository(session)
            checkpoint_repo = CheckpointRepository(session)
            run = run_repo.get(run_id)
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
            checkpoint = checkpoint_repo.latest_for_run(run_id)
            data = {
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "status": run.status,
                "checkpoint_token": checkpoint.checkpoint_token if checkpoint else run.checkpoint_token,
                "processed_items": run.processed_items,
            }
        _emit(JsonResponse(ok=True, data=data).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("deployment:check")
def deployment_check_command(
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Validate configuration and database connectivity for deployment."""

    try:
        container = RuntimeContainer(config)
        with container.session_factory.engine.connect():
            pass
        _emit(
            JsonResponse(
                ok=True,
                data={
                    "deployment": {
                        "config_path": str(config),
                        "database": _safe_database_details(container.config.database_url),
                        "status": "ok",
                    }
                },
            ).to_dict()
        )
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)
