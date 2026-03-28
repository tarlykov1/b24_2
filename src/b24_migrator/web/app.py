from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from b24_migrator.errors import AppError
from b24_migrator.services.runtime import RuntimeService
from b24_migrator.web.routes.ui import router as ui_router

security = HTTPBasic()


def create_app(config_path: str | None = None) -> FastAPI:
    app = FastAPI(title="b24-migration-web", version="0.1.0")
    base_dir = Path(__file__).resolve().parent
    selected_config = Path(config_path or os.getenv("MIGRATION_CONFIG_PATH", "migration.config.yml"))

    app.state.config_path = selected_config
    app.state.runtime_service = RuntimeService(selected_config)
    app.state.runtime_service.ensure_schema()
    app.state.templates = Jinja2Templates(directory=str(base_dir / "templates"))

    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

    @app.middleware("http")
    async def basic_auth_middleware(request: Request, call_next):
        username = os.getenv("B24_WEB_USERNAME")
        password = os.getenv("B24_WEB_PASSWORD")
        if not username or not password:
            request.state.actor = "anonymous"
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Basic "):
            return JSONResponse({"ok": False, "error_code": "AUTH_REQUIRED", "message": "Authentication required"}, status_code=401, headers={"WWW-Authenticate": "Basic"})

        try:
            credentials: HTTPBasicCredentials = await security(request)
        except HTTPException:
            return JSONResponse({"ok": False, "error_code": "AUTH_INVALID", "message": "Invalid authentication"}, status_code=401, headers={"WWW-Authenticate": "Basic"})

        is_valid = secrets.compare_digest(credentials.username, username) and secrets.compare_digest(credentials.password, password)
        if not is_valid:
            return JSONResponse({"ok": False, "error_code": "AUTH_INVALID", "message": "Invalid authentication"}, status_code=401, headers={"WWW-Authenticate": "Basic"})

        request.state.actor = credentials.username
        return await call_next(request)

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError):
        status_code = 400 if exc.code.startswith(("CONFIG_", "VALIDATION_")) else 404 if exc.code.endswith("NOT_FOUND") else 500
        return JSONResponse(exc.to_dict(), status_code=status_code)

    app.include_router(ui_router)
    return app


app = create_app()
