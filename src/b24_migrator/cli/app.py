from __future__ import annotations

import json
from pathlib import Path

import typer

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
        self.session_factory = SessionFactory(self.config.database_url)
        self.planner = PlannerService()
        self.executor = ExecutionService()
        self.verifier = VerificationService()

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self.session_factory.engine)


def _emit(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _handle_error(exc: AppError) -> None:
    _emit(exc.to_dict())
    raise typer.Exit(code=2)


@app.command("plan")
def plan_command(
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
    scope: list[str] = typer.Option([], "--scope", help="Repeatable scope override."),
) -> None:
    """Create and persist deterministic migration plan."""

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

        _emit(JsonResponse(ok=True, data={"plan": plan.__dict__}).to_dict())
    except AppError as exc:
        _handle_error(exc)


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

        _emit(JsonResponse(ok=True, data={"run": result.__dict__}).to_dict())
    except AppError as exc:
        _handle_error(exc)


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

        _emit(JsonResponse(ok=True, data={"run": resumed.__dict__}).to_dict())
    except AppError as exc:
        _handle_error(exc)


@app.command("verify")
def verify_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("migration.config.yml"), "--config"),
) -> None:
    """Run deterministic verification checks for stored run."""

    try:
        container = RuntimeContainer(config)
        with container.session_factory.create_session() as session:
            run_repo = RunRepository(session)
            run = run_repo.get(run_id)
            if run is None:
                raise AppError("RUN_NOT_FOUND", "Run does not exist", {"run_id": run_id})
            report = container.verifier.verify_run(run)

        _emit(JsonResponse(ok=True, data={"verification": report}).to_dict())
    except AppError as exc:
        _handle_error(exc)


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
