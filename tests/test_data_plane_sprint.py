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
  - users
  - tasks
""",
        encoding="utf-8",
    )
    return config_path


def test_user_matching_and_manual_review_override(tmp_path: Path) -> None:
    svc = RuntimeService(_write_config(tmp_path))
    svc.ensure_schema()
    out = svc.users_map(
        source_users=[
            {"id": "1", "xml_id": "u1", "email": "a@x.tld", "login": "alice"},
            {"id": "2", "xml_id": "u2", "email": "b@x.tld", "login": "bob"},
        ],
        target_users=[
            {"id": "11", "xml_id": "u1", "email": "a@x.tld", "login": "alice"},
            {"id": "21", "xml_id": "u2", "email": "dup@x.tld", "login": "bob"},
            {"id": "22", "xml_id": "u2", "email": "dup2@x.tld", "login": "bob2"},
        ],
    )
    assert out["resolved"] == 1
    assert out["ambiguous"] == 1
    assert len(svc.list_user_review_queue()) == 1

    reviewed = svc.users_review(source_id="2", target_id="22")
    assert reviewed["status"] == "resolved"
    assert svc.list_user_review_queue() == []


def test_unresolved_user_blocks_groups_and_tasks(tmp_path: Path) -> None:
    svc = RuntimeService(_write_config(tmp_path))
    svc.ensure_schema()
    svc.users_map(source_users=[{"id": "1", "xml_id": "u1"}], target_users=[{"id": "11", "xml_id": "u1"}])

    groups = svc.groups_sync(
        source_groups=[{"id": "10", "xml_id": "g10", "name": "Dev", "member_user_ids": ["1", "404"]}],
        target_groups=[],
    )
    assert groups["blocked"] == 1

    tasks = svc.tasks_migrate(
        [
            {
                "id": "100",
                "xml_id": "t100",
                "author_id": "1",
                "responsible_id": "404",
                "group_id": "10",
            }
        ]
    )
    assert tasks["blocked"] == 1
    task_mapping = svc.list_mappings(entity_type="tasks")[0]
    assert task_mapping.status == "error"


def test_comments_and_file_refs_relation_and_partial_files(tmp_path: Path) -> None:
    svc = RuntimeService(_write_config(tmp_path))
    svc.ensure_schema()
    plan = svc.create_plan()["plan"]
    run = svc.execute_plan(plan_id=plan.plan_id)

    svc.users_map(source_users=[{"id": "1", "xml_id": "u1"}], target_users=[{"id": "11", "xml_id": "u1"}])
    svc.groups_sync(source_groups=[{"id": "10", "xml_id": "g10", "name": "Dev", "member_user_ids": ["1"]}], target_groups=[])
    svc.tasks_migrate([{"id": "100", "author_id": "1", "responsible_id": "1", "group_id": "10"}])
    svc.comments_migrate([{"id": "500", "task_id": "100", "author_id": "1", "body": "ok"}])
    svc.file_refs_migrate([{"id": "700", "task_id": "100", "name": "spec.pdf", "size": 10, "mime": "application/pdf"}])

    report = svc.get_report(run_id=run.run_id)
    files_check = [r for r in report["verification_results"] if r.check_type == "verify:files"][0]
    assert files_check.status == "partial"
    assert files_check.details["payload_copy"] == "partial_planned"
