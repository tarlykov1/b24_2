from __future__ import annotations

from pathlib import Path

from b24_migrator.services.runtime import RuntimeService


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


def test_mapping_upsert_and_user_conflict_queue(tmp_path: Path) -> None:
    svc = RuntimeService(_write_config(tmp_path))
    svc.ensure_schema()

    first = svc.upsert_mapping(
        entity_type="tasks",
        source_id="10",
        source_uid="task-10",
        target_id="100",
        target_uid="task-100",
        status="resolved",
        resolution_strategy="direct",
        payload={"name": "task"},
    )
    assert first.entity_type == "tasks"

    rows = svc.list_mappings(entity_type="tasks")
    assert len(rows) == 1
    assert rows[0].target_id == "100"

    ambiguous = svc.resolve_user_mapping(
        source_user={"id": "1", "xml_id": "abc", "email": "a@x.tld", "login": "alice"},
        target_candidates=[
            {"id": "11", "xml_id": "abc", "email": "a@x.tld", "login": "alice"},
            {"id": "12", "xml_id": "abc", "email": "b@x.tld", "login": "alice2"},
        ],
    )
    assert ambiguous["status"] == "open"
    queue = svc.list_user_review_queue()
    assert len(queue) == 1


def test_verification_results_persisted(tmp_path: Path) -> None:
    svc = RuntimeService(_write_config(tmp_path))
    svc.ensure_schema()
    plan = svc.create_plan()["plan"]
    run = svc.execute_plan(plan_id=plan.plan_id)
    svc.upsert_mapping(
        entity_type="tasks",
        source_id="10",
        source_uid="task-10",
        target_id="100",
        target_uid="task-100",
        status="resolved",
        resolution_strategy="direct",
        linked_parent_type="users",
        linked_parent_source_id="1",
        linked_parent_target_id="11",
    )

    report = svc.get_report(run_id=run.run_id)
    assert report["verification"]["all_passed"] is True
    assert len(report["verification_results"]) >= 4

    rows = svc.verification_results(run.run_id)
    assert any(r["check_type"] == "verify:relations" for r in rows)
