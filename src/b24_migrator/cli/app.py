from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from b24_migrator.cli.exit_codes import ExitCode
from b24_migrator.config import load_runtime_config
from b24_migrator.domain.models import ExecutionResult
from b24_migrator.errors import AppError
from b24_migrator.schemas import JsonResponse
from b24_migrator.services.executor import ExecutionService
from b24_migrator.services.planner import PlannerService
from b24_migrator.services.verifier import VerificationService
from b24_migrator.storage.base import Base
from b24_migrator.storage.repositories import PlanRepository, RunRepository
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
    return value.__dict__.copy() if hasattr(value, "__dict__") else dict(value)


def _job_payload_from_plan(plan: Any) -> dict[str, Any]:
    payload = _asdict(plan)
    payload["job_id"] = payload["plan_id"]
    return payload


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


@app.command("create-job")
def create_job_command(
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
    scope: list[str] = typer.Option([], "--scope", help="Repeatable scope override."),
) -> None:
    """Create and persist deterministic migration job plan."""

    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        final_scope = scope or container.config.default_scope
        plan = container.planner.create_plan(
            source_portal=container.config.source.base_url,
            target_portal=container.config.target.base_url,
            scope=final_scope,
        )
        with container.session_factory.create_session() as session:
            repo = PlanRepository(session)
            repo.save(plan)
            session.commit()

        _emit(JsonResponse(ok=True, data={"job": _job_payload_from_plan(plan)}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("status")
def status_command(
    plan_id: str | None = typer.Option(None, "--plan-id"),
    run_id: str | None = typer.Option(None, "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Return current status of a migration plan or run."""

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
            if run_id:
                run = run_repo.get(run_id)
                if run is None:
                    raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
                _emit(JsonResponse(ok=True, data={"run": _asdict(run)}).to_dict())
                return

            assert plan_id is not None
            plan = plan_repo.get(plan_id)
            if plan is None:
                raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": plan_id})
            latest = run_repo.find_latest_for_plan(plan_id)
            payload: dict[str, Any] = {"plan": _asdict(plan)}
            if latest is not None:
                payload["latest_run"] = _asdict(latest)
            _emit(JsonResponse(ok=True, data=payload).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("report")
def report_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Return verification report for a stored run."""

    try:
        container = RuntimeContainer(config)
        with container.session_factory.create_session() as session:
            run_repo = RunRepository(session)
            run = run_repo.get(run_id)
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
            report = container.verifier.verify_run(run)

        _emit(JsonResponse(ok=True, data={"verification": report, "run": _asdict(run)}).to_dict())
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


@app.command("plan")
def plan_command(
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
    scope: list[str] = typer.Option([], "--scope", help="Repeatable scope override."),
) -> None:
    """Backward-compatible alias for create-job."""

    create_job_command(config=config, scope=scope)


@app.command("execute")
def execute_command(
    plan_id: str = typer.Option(..., "--plan-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Execute migration plan with checkpoint persistence."""

    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        with container.session_factory.create_session() as session:
            plan_repo = PlanRepository(session)
            run_repo = RunRepository(session)
            plan = plan_repo.get(plan_id)
            if plan is None:
                raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": plan_id})
            result = container.executor.execute(plan=plan, dry_run=dry_run)
            run_repo.save(result)
            session.commit()

        _emit(JsonResponse(ok=True, data={"run": _asdict(result)}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("resume")
def resume_command(
    plan_id: str = typer.Option(..., "--plan-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Resume execution from latest stored checkpoint for plan."""

    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        with container.session_factory.create_session() as session:
            plan_repo = PlanRepository(session)
            run_repo = RunRepository(session)
            plan = plan_repo.get(plan_id)
            if plan is None:
                raise AppError("PLAN_NOT_FOUND", "Migration plan does not exist", {"plan_id": plan_id})
            latest = run_repo.find_latest_for_plan(plan_id)
            if latest is None:
                raise AppError("RUN_NOT_FOUND", "No execution to resume", {"plan_id": plan_id})
            resumed = container.executor.execute(plan=plan, dry_run=False, resume_from=latest)
            run_repo.save(resumed)
            session.commit()

        _emit(JsonResponse(ok=True, data={"run": _asdict(resumed)}).to_dict())
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
            run: ExecutionResult | None = run_repo.get(run_id)
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
            data = {
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "status": run.status,
                "checkpoint_token": run.checkpoint_token,
                "processed_items": run.processed_items,
            }
        _emit(JsonResponse(ok=True, data=data).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)
