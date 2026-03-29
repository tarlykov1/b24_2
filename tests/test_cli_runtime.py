import json
from pathlib import Path

from typer.testing import CliRunner

from b24_migrator.cli.app import _asdict, app
from b24_migrator.cli.exit_codes import ExitCode

runner = CliRunner()


def test_asdict_serializes_slots_dataclass() -> None:
    class _SlotsDictLike:
        def __iter__(self):
            return iter((("k", "v"),))

    from datetime import datetime, timezone

    from b24_migrator.domain.models import Job

    job = Job(
        job_id="job-1",
        source_portal="https://source",
        target_portal="https://target",
        created_at=datetime.now(tz=timezone.utc),
    )
    payload = _asdict(job)
    assert payload["job_id"] == "job-1"
    assert _asdict({"a": 1}) == {"a": 1}
    assert _asdict(_SlotsDictLike()) == {"k": "v"}


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


def test_lifecycle_create_job_plan_execute_status_report_resume(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    create_job = runner.invoke(app, ["create-job", "--config", str(config_path)])
    assert create_job.exit_code == ExitCode.SUCCESS
    create_payload = json.loads(create_job.stdout)
    job_id = create_payload["data"]["job"]["job_id"]

    create_plan = runner.invoke(app, ["plan", "--config", str(config_path), "--job-id", job_id])
    assert create_plan.exit_code == ExitCode.SUCCESS
    plan_payload = json.loads(create_plan.stdout)
    plan_id = plan_payload["data"]["plan"]["plan_id"]
    assert plan_payload["data"]["plan"]["job_id"] == job_id

    execute = runner.invoke(app, ["execute", "--config", str(config_path), "--plan-id", plan_id])
    assert execute.exit_code == ExitCode.SUCCESS
    run_id = json.loads(execute.stdout)["data"]["run"]["run_id"]

    status = runner.invoke(app, ["status", "--config", str(config_path), "--plan-id", plan_id])
    assert status.exit_code == ExitCode.SUCCESS
    status_payload = json.loads(status.stdout)
    assert status_payload["data"]["plan"]["plan_id"] == plan_id
    assert status_payload["data"]["latest_run"]["run_id"] == run_id

    report = runner.invoke(app, ["report", "--config", str(config_path), "--run-id", run_id])
    assert report.exit_code == ExitCode.SUCCESS
    report_payload = json.loads(report.stdout)
    assert report_payload["data"]["run"]["run_id"] == run_id
    assert report_payload["data"]["logs"]

    resume = runner.invoke(app, ["resume", "--config", str(config_path), "--plan-id", plan_id])
    assert resume.exit_code == ExitCode.SUCCESS
    resumed = json.loads(resume.stdout)["data"]["run"]
    assert resumed["run_id"] == run_id
    assert resumed["processed_items"] > 0


def test_plan_without_job_id_backfills_job_for_backward_compatibility(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    result = runner.invoke(app, ["plan", "--config", str(config_path)])

    assert result.exit_code == ExitCode.SUCCESS
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["job"]["job_id"] == payload["data"]["plan"]["job_id"]


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


def test_enterprise_cli_surfaces(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    plan_payload = json.loads(runner.invoke(app, ["plan", "--config", str(config_path)]).stdout)
    plan_id = plan_payload["data"]["plan"]["plan_id"]
    run_id = json.loads(runner.invoke(app, ["execute", "--config", str(config_path), "--plan-id", plan_id]).stdout)["data"]["run"]["run_id"]

    matrix = runner.invoke(app, ["matrix", "--config", str(config_path)])
    assert matrix.exit_code == ExitCode.SUCCESS
    assert len(json.loads(matrix.stdout)["data"]["matrix"]) >= 10

    domains = runner.invoke(app, ["domains", "--config", str(config_path)])
    assert domains.exit_code == ExitCode.SUCCESS

    cleanup = runner.invoke(app, ["cleanup:plan", "--config", str(config_path)])
    assert cleanup.exit_code == ExitCode.SUCCESS
    assert json.loads(cleanup.stdout)["data"]["cleanup_plan"]["dry_run"] is True

    delta = runner.invoke(app, ["delta:plan", "--config", str(config_path)])
    assert delta.exit_code == ExitCode.SUCCESS

    # populate verification rows first
    runner.invoke(app, ["report", "--config", str(config_path), "--run-id", run_id])
    verify_rows = runner.invoke(app, ["verify:results", "--config", str(config_path), "--run-id", run_id])
    assert verify_rows.exit_code == ExitCode.SUCCESS


def test_new_data_plane_cli_commands(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    users_map = runner.invoke(
        app,
        [
            "users:map",
            "--config",
            str(config_path),
            "--source-users-json",
            '[{"id":"1","xml_id":"u1"},{"id":"2","xml_id":"u2"}]',
            "--target-users-json",
            '[{"id":"11","xml_id":"u1"},{"id":"21","xml_id":"u2"},{"id":"22","xml_id":"u2"}]',
        ],
    )
    assert users_map.exit_code == ExitCode.SUCCESS
    assert json.loads(users_map.stdout)["data"]["users_map"]["ambiguous"] == 1

    users_review = runner.invoke(app, ["users:review", "--config", str(config_path), "--source-id", "2", "--target-id", "21"])
    assert users_review.exit_code == ExitCode.SUCCESS

    groups = runner.invoke(
        app,
        [
            "groups:sync",
            "--config",
            str(config_path),
            "--source-groups-json",
            '[{"id":"10","name":"Dev","member_user_ids":["1","2"]}]',
            "--target-groups-json",
            "[]",
        ],
    )
    assert groups.exit_code == ExitCode.SUCCESS

    tasks = runner.invoke(
        app,
        ["tasks:migrate", "--config", str(config_path), "--source-tasks-json", '[{"id":"100","author_id":"1","responsible_id":"2","group_id":"10"}]'],
    )
    assert tasks.exit_code == ExitCode.SUCCESS

    crm_sync = runner.invoke(
        app,
        [
            "crm:sync",
            "--config",
            str(config_path),
            "--source-categories-json",
            '[{"id":"10","code":"PIPE_A","name":"A"}]',
            "--target-categories-json",
            '[{"id":"110","code":"PIPE_A","name":"A"}]',
            "--source-stages-json",
            '[{"id":"20","code":"STAGE_NEW","name":"New"}]',
            "--target-stages-json",
            '[{"id":"120","code":"STAGE_NEW","name":"New"}]',
            "--source-custom-fields-json",
            '[{"id":"30","code":"UF_1","type":"string"}]',
            "--target-custom-fields-json",
            '[{"id":"130","code":"UF_1"}]',
        ],
    )
    assert crm_sync.exit_code == ExitCode.SUCCESS
