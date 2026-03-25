import json
from pathlib import Path

from typer.testing import CliRunner

from b24_migrator.cli.app import app
from b24_migrator.cli.exit_codes import ExitCode

runner = CliRunner()


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "migration.config.yml"
    db_path = tmp_path / "runtime.db"
    config_path.write_text(
        f"""
        runtime_mode: test
        database_url: sqlite+pysqlite:///{db_path}
        source:
          base_url: https://source
          webhook: one
        target:
          base_url: https://target
          webhook: two
        default_scope:
          - crm
          - tasks
        """,
        encoding="utf-8",
    )
    return config_path


def test_create_job_returns_explicit_job_payload(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    result = runner.invoke(app, ["create-job", "--config", str(config_path)])

    assert result.exit_code == ExitCode.SUCCESS
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["job"]["source_portal"] == "https://source"
    assert payload["data"]["job"]["job_id"] == payload["data"]["job"]["plan_id"]


def test_status_for_plan_includes_latest_run_after_execute(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    create = runner.invoke(app, ["create-job", "--config", str(config_path)])
    plan_id = json.loads(create.stdout)["data"]["job"]["plan_id"]
    runner.invoke(app, ["execute", "--config", str(config_path), "--plan-id", plan_id])

    result = runner.invoke(app, ["status", "--config", str(config_path), "--plan-id", plan_id])

    assert result.exit_code == ExitCode.SUCCESS
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["plan"]["plan_id"] == plan_id
    assert payload["data"]["latest_run"]["plan_id"] == plan_id


def test_deployment_check_returns_sanitized_database_output(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(tmp_path)
    from b24_migrator.cli import app as cli_app

    class _FakeConnect:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeEngine:
        def connect(self):
            return _FakeConnect()

    class _FakeSessionFactory:
        engine = _FakeEngine()

    class _FakeConfig:
        database_url = "mysql+pymysql://runtime_user:super_secret@db.internal:3306/b24_runtime"

    class _FakeContainer:
        def __init__(self, _config_path):
            self.config = _FakeConfig()
            self.session_factory = _FakeSessionFactory()

    monkeypatch.setattr(cli_app, "RuntimeContainer", _FakeContainer)

    result = runner.invoke(app, ["deployment:check", "--config", str(config_path)])

    assert result.exit_code == ExitCode.SUCCESS
    payload = json.loads(result.stdout)
    db_payload = payload["data"]["deployment"]["database"]
    assert db_payload["username"] == "runtime_user"
    assert db_payload["dsn"].startswith("mysql+pymysql://runtime_user:***@db.internal")
    assert "super_secret" not in db_payload["dsn"]


def test_status_requires_identifier(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    result = runner.invoke(app, ["status", "--config", str(config_path)])

    assert result.exit_code == ExitCode.VALIDATION_ERROR
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_code"] == "VALIDATION_MISSING_IDENTIFIER"
