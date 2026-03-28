from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import typer
from sqlalchemy.exc import SQLAlchemyError

from b24_migrator.cli.exit_codes import ExitCode
from b24_migrator.errors import AppError
from b24_migrator.schemas import JsonResponse
from b24_migrator.services.runtime import RuntimeService, safe_database_details

app = typer.Typer(help="Bitrix24 deterministic migration runtime")


class RuntimeContainer:
    """Backward-compatible wrapper used by CLI and older tests."""

    def __init__(self, config_path: Path) -> None:
        self.service = RuntimeService(config_path)
        self.config = self.service.config
        self.session_factory = self.service.session_factory

    def ensure_schema(self) -> None:
        self.service.ensure_schema()


def _emit(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


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


@app.command("create-job")
def create_job_command(config: Path = typer.Option(Path("migration.config.yml"), "--config")) -> None:
    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        job = container.service.create_job()
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
    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        payload = container.service.create_plan(job_id=job_id, scope=scope or None)
        _emit(JsonResponse(ok=True, data={k: _asdict(v) for k, v in payload.items()}).to_dict())
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
    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        payload = container.service.get_status(job_id=job_id, plan_id=plan_id, run_id=run_id)
        _emit(
            JsonResponse(
                ok=True,
                data={k: [_asdict(i) for i in v] if isinstance(v, list) else _asdict(v) for k, v in payload.items()},
            ).to_dict()
        )
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
    try:
        container = RuntimeContainer(config)
        container.ensure_schema()
        run = container.service.execute_plan(plan_id=plan_id, dry_run=dry_run)
        _emit(JsonResponse(ok=True, data={"run": _asdict(run)}).to_dict())
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
    try:
        if not plan_id and not run_id:
            raise AppError(
                code="VALIDATION_MISSING_IDENTIFIER",
                message="Either --plan-id or --run-id must be provided",
            )
        container = RuntimeContainer(config)
        container.ensure_schema()
        run = container.service.resume_run(plan_id=plan_id, run_id=run_id)
        _emit(JsonResponse(ok=True, data={"run": _asdict(run)}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("report")
def report_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    try:
        container = RuntimeContainer(config)
        payload = container.service.get_report(run_id=run_id)
        _emit(JsonResponse(ok=True, data={k: [_asdict(i) for i in v] if isinstance(v, list) else _asdict(v) for k, v in payload.items()}).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("verify")
def verify_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    report_command(run_id=run_id, config=config)


@app.command("checkpoint")
def checkpoint_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    try:
        container = RuntimeContainer(config)
        payload = container.service.get_checkpoint(run_id=run_id)
        _emit(JsonResponse(ok=True, data=payload).to_dict())
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)


@app.command("deployment:check")
def deployment_check_command(config: Path = typer.Option(Path("migration.config.yml"), "--config")) -> None:
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
                        "database": safe_database_details(container.config.database_url),
                        "status": "ok",
                    }
                },
            ).to_dict()
        )
    except AppError as exc:
        _handle_error(exc)
    except SQLAlchemyError as exc:
        _handle_sqlalchemy_error(exc)
