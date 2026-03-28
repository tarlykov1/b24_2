import pytest

pytest.importorskip("fastapi")

from pathlib import Path

from fastapi.testclient import TestClient

from b24_migrator.web.app import create_app


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


def test_health_jobs_plan_execute_and_audit(tmp_path: Path) -> None:
    app = create_app(str(_write_config(tmp_path)))
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    created_job = client.post("/jobs").json()["data"]["job"]
    created_plan = client.post("/plans", data={"job_id": created_job["job_id"]}).json()["data"]["plan"]
    run = client.post("/runs/execute", data={"plan_id": created_plan["plan_id"], "dry_run": "false"}).json()["data"]["run"]

    run_status = client.get(f"/runs/{run['run_id']}")
    assert run_status.status_code == 200
    assert run_status.json()["data"]["run"]["run_id"] == run["run_id"]

    audit = client.get("/audit")
    assert audit.status_code == 200
    assert len(audit.json()["data"]["audit"]) >= 3


def test_config_save_and_test(tmp_path: Path) -> None:
    app = create_app(str(_write_config(tmp_path)))
    client = TestClient(app)

    resp = client.post("/config/test")
    assert resp.status_code == 200

    save_payload = {
        "runtime_mode": "test",
        "database_url": f"sqlite+pysqlite:///{tmp_path / 'runtime2.db'}",
        "source_base_url": "https://source2",
        "source_webhook": "new-source-webhook",
        "target_base_url": "https://target2",
        "target_webhook": "new-target-webhook",
        "default_scope": "crm,tasks",
    }
    saved = client.post("/config/save", data=save_payload)
    assert saved.status_code == 200
    assert saved.json()["data"]["saved"] is True
