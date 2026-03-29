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


def test_enterprise_endpoints(tmp_path: Path) -> None:
    app = create_app(str(_write_config(tmp_path)))
    client = TestClient(app)

    plan = client.post("/plans").json()["data"]["plan"]
    run = client.post("/runs/execute", data={"plan_id": plan["plan_id"], "dry_run": "false"}).json()["data"]["run"]

    matrix = client.get("/matrix")
    assert matrix.status_code == 200
    assert len(matrix.json()["data"]["matrix"]) >= 10

    domains = client.get("/domains")
    assert domains.status_code == 200
    assert len(domains.json()["data"]["dependency_graph"]) == 12

    mapped = client.get("/mappings")
    assert mapped.status_code == 200

    preview = client.get("/cleanup/preview")
    assert preview.status_code == 200
    assert preview.json()["data"]["cleanup_plan"]["dry_run"] is True

    delta = client.get("/delta")
    assert delta.status_code == 200
    assert delta.json()["data"]["delta_plan"]["resume_supported"] is True

    report = client.get(f"/runs/{run['run_id']}/report")
    assert report.status_code == 200

    verify_rows = client.get(f"/verification/{run['run_id']}")
    assert verify_rows.status_code == 200

    cutover = client.get(f"/cutover/{run['run_id']}")
    assert cutover.status_code == 200
    assert "ready" in cutover.json()["data"]["cutover_readiness"]

    enterprise = client.get("/enterprise")
    assert enterprise.status_code == 200


def test_mapping_review_and_data_plane_endpoints(tmp_path: Path) -> None:
    app = create_app(str(_write_config(tmp_path)))
    client = TestClient(app)

    users_map = client.post(
        "/users/map",
        data={
            "source_users_json": '[{"id":"1","xml_id":"u1"},{"id":"2","xml_id":"u2"}]',
            "target_users_json": '[{"id":"11","xml_id":"u1"},{"id":"21","xml_id":"u2"},{"id":"22","xml_id":"u2"}]',
        },
    )
    assert users_map.status_code == 200
    assert users_map.json()["data"]["users_map"]["ambiguous"] == 1

    review = client.post("/users/review/resolve", data={"source_id": "2", "target_id": "21"})
    assert review.status_code == 200

    groups = client.post(
        "/groups/sync",
        data={"source_groups_json": '[{"id":"10","name":"Dev","member_user_ids":["1","2"]}]', "target_groups_json": "[]"},
    )
    assert groups.status_code == 200

    tasks = client.post(
        "/tasks/migrate",
        data={"source_tasks_json": '[{"id":"100","author_id":"1","responsible_id":"2","group_id":"10"}]'},
    )
    assert tasks.status_code == 200

    comments = client.post("/comments/migrate", data={"source_comments_json": '[{"id":"500","task_id":"100","author_id":"1","body":"x"}]'})
    assert comments.status_code == 200
    files = client.post("/files/refs/migrate", data={"source_refs_json": '[{"id":"700","task_id":"100","name":"a.txt"}]'})
    assert files.status_code == 200
