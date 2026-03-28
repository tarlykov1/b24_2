from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from b24_migrator.config import RuntimeConfig
from b24_migrator.errors import AppError
from b24_migrator.services.runtime import RuntimeService, save_config

router = APIRouter()


def _serialize(value: Any) -> Any:
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


def get_runtime_service(request: Request) -> RuntimeService:
    return request.app.state.runtime_service


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def current_actor(request: Request) -> str:
    return getattr(request.state, "actor", "anonymous")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, svc: RuntimeService = Depends(get_runtime_service), templates: Jinja2Templates = Depends(get_templates)):
    jobs = svc.list_jobs(limit=10)
    plans = svc.list_plans(limit=10)
    runs = svc.list_runs(limit=10)
    audit = svc.list_audit(limit=10)
    last_errors = [asdict(item) for item in svc.list_logs(run_id=runs[0].run_id, level="ERROR")] if runs else []
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "jobs": [asdict(job) for job in jobs],
            "plans": [asdict(plan) for plan in plans],
            "runs": [asdict(run) for run in runs],
            "audit": [asdict(entry) for entry in audit],
            "last_errors": last_errors,
        },
    )


@router.get("/health")
def health(svc: RuntimeService = Depends(get_runtime_service)) -> dict[str, Any]:
    deployment = svc.validate_deployment()
    return {"ok": True, "data": {"deployment": deployment}}


@router.get("/config", response_class=HTMLResponse)
def config_screen(request: Request, svc: RuntimeService = Depends(get_runtime_service), templates: Jinja2Templates = Depends(get_templates)):
    masked = svc.config.model_dump(mode="python")
    masked["source"]["webhook"] = _mask_secret(masked["source"]["webhook"])
    masked["target"]["webhook"] = _mask_secret(masked["target"]["webhook"])
    return templates.TemplateResponse(request, "config.html", {"config": masked})


@router.post("/config/test")
def test_config(svc: RuntimeService = Depends(get_runtime_service), actor: str = Depends(current_actor)) -> dict[str, Any]:
    deployment = svc.validate_deployment()
    return {"ok": True, "data": {"deployment": deployment, "actor": actor}}


@router.post("/config/save")
def save_config_route(
    request: Request,
    runtime_mode: str = Form(...),
    database_url: str = Form(...),
    source_base_url: str = Form(...),
    source_webhook: str = Form(...),
    target_base_url: str = Form(...),
    target_webhook: str = Form(...),
    default_scope: str = Form("crm,tasks"),
    svc: RuntimeService = Depends(get_runtime_service),
    actor: str = Depends(current_actor),
) -> dict[str, Any]:
    payload = {
        "runtime_mode": runtime_mode,
        "database_url": database_url,
        "source": {"base_url": source_base_url, "webhook": source_webhook},
        "target": {"base_url": target_base_url, "webhook": target_webhook},
        "default_scope": [item.strip() for item in default_scope.split(",") if item.strip()],
    }
    try:
        config = RuntimeConfig.model_validate(payload)
    except Exception as exc:  # validation from pydantic
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_config(Path(request.app.state.config_path), config)
    request.app.state.runtime_service = RuntimeService(Path(request.app.state.config_path))
    request.app.state.runtime_service.ensure_schema()
    return {"ok": True, "data": {"saved": True, "actor": actor}}


@router.get("/jobs")
def list_jobs(svc: RuntimeService = Depends(get_runtime_service), limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    return {"ok": True, "data": {"jobs": _serialize(svc.list_jobs(limit=limit))}}


@router.post("/jobs")
def create_job(svc: RuntimeService = Depends(get_runtime_service), actor: str = Depends(current_actor)) -> dict[str, Any]:
    job = svc.create_job(actor=actor)
    return {"ok": True, "data": {"job": asdict(job)}}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, svc: RuntimeService = Depends(get_runtime_service)) -> dict[str, Any]:
    return {"ok": True, "data": _serialize(svc.get_status(job_id=job_id))}


@router.post("/plans")
def create_plan(
    svc: RuntimeService = Depends(get_runtime_service),
    actor: str = Depends(current_actor),
    job_id: str | None = Form(default=None),
    scope: str | None = Form(default=None),
) -> dict[str, Any]:
    scope_list = [item.strip() for item in scope.split(",") if item.strip()] if scope else None
    payload = svc.create_plan(job_id=job_id, scope=scope_list, actor=actor)
    return {"ok": True, "data": _serialize(payload)}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, svc: RuntimeService = Depends(get_runtime_service)) -> dict[str, Any]:
    return {"ok": True, "data": _serialize(svc.get_status(plan_id=plan_id))}


@router.post("/runs/execute")
def execute_plan(
    plan_id: str = Form(...),
    dry_run: bool = Form(default=False),
    svc: RuntimeService = Depends(get_runtime_service),
    actor: str = Depends(current_actor),
) -> dict[str, Any]:
    run = svc.execute_plan(plan_id=plan_id, dry_run=dry_run, actor=actor)
    return {"ok": True, "data": {"run": asdict(run)}}


@router.post("/runs/resume")
def resume_run(
    plan_id: str | None = Form(default=None),
    run_id: str | None = Form(default=None),
    svc: RuntimeService = Depends(get_runtime_service),
    actor: str = Depends(current_actor),
) -> dict[str, Any]:
    run = svc.resume_run(plan_id=plan_id, run_id=run_id, actor=actor)
    return {"ok": True, "data": {"run": asdict(run)}}


@router.get("/runs")
def list_runs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    svc: RuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return {"ok": True, "data": {"runs": _serialize(svc.list_runs(limit=limit, status=status_filter))}}


@router.get("/runs/{run_id}")
def get_run(run_id: str, svc: RuntimeService = Depends(get_runtime_service)) -> dict[str, Any]:
    status_payload = svc.get_status(run_id=run_id)
    checkpoint = svc.get_checkpoint(run_id=run_id)
    return {"ok": True, "data": {"run": _serialize(status_payload["run"]), "checkpoint": checkpoint}}


@router.get("/runs/{run_id}/logs")
def run_logs(
    run_id: str,
    level: str | None = Query(default=None),
    svc: RuntimeService = Depends(get_runtime_service),
) -> dict[str, Any]:
    return {"ok": True, "data": {"logs": _serialize(svc.list_logs(run_id=run_id, level=level))}}


@router.get("/runs/{run_id}/report")
def run_report(run_id: str, svc: RuntimeService = Depends(get_runtime_service)) -> dict[str, Any]:
    return {"ok": True, "data": _serialize(svc.get_report(run_id=run_id))}


@router.get("/runs/{run_id}/checkpoint")
def run_checkpoint(run_id: str, svc: RuntimeService = Depends(get_runtime_service)) -> dict[str, Any]:
    return {"ok": True, "data": svc.get_checkpoint(run_id=run_id)}


@router.get("/audit")
def list_audit(svc: RuntimeService = Depends(get_runtime_service), limit: int = Query(default=200, ge=1, le=1000)) -> dict[str, Any]:
    return {"ok": True, "data": {"audit": _serialize(svc.list_audit(limit=limit))}}


@router.get("/runs/{run_id}/view", response_class=HTMLResponse)
def run_view(request: Request, run_id: str, svc: RuntimeService = Depends(get_runtime_service), templates: Jinja2Templates = Depends(get_templates)):
    data = get_run(run_id, svc)
    logs = run_logs(run_id, svc=svc)
    return templates.TemplateResponse(request, "run.html", {"run": data["data"]["run"], "checkpoint": data["data"]["checkpoint"], "logs": logs["data"]["logs"]})


def _mask_secret(raw: str) -> str:
    if len(raw) <= 6:
        return "***"
    return f"{raw[:3]}***{raw[-2:]}"
