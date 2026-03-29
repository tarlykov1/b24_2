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


def test_crm_data_plane_relations_and_blocking(tmp_path: Path) -> None:
    svc = RuntimeService(_write_config(tmp_path))
    svc.ensure_schema()
    plan = svc.create_plan()["plan"]
    run = svc.execute_plan(plan_id=plan.plan_id)

    svc.users_map(source_users=[{"id": "1", "xml_id": "u1"}, {"id": "2", "xml_id": "u2"}], target_users=[{"id": "11", "xml_id": "u1"}, {"id": "12", "xml_id": "u2"}])
    crm_sync = svc.crm_sync(
        source_categories=[{"id": "10", "code": "PIPE_A", "name": "Pipeline A"}],
        target_categories=[{"id": "110", "code": "PIPE_A", "name": "Pipeline A"}],
        source_stages=[{"id": "20", "code": "STAGE_NEW", "name": "New"}],
        target_stages=[{"id": "120", "code": "STAGE_NEW", "name": "New"}],
        source_custom_fields=[{"id": "30", "code": "UF_CRM_1", "type": "string"}, {"id": "31", "code": "UF_CRM_2", "type": "disk_file"}],
        target_custom_fields=[{"id": "130", "code": "UF_CRM_1"}],
    )
    assert crm_sync["custom_fields"]["implemented"] == 1
    assert crm_sync["custom_fields"]["unsupported"] == 1

    contacts = svc.crm_contacts_migrate(
        source_contacts=[{"id": "200", "xml_id": "c200", "responsible_id": "1", "custom_fields": {"30": "x"}}],
        target_contacts=[{"id": "220", "xml_id": "c200"}],
    )
    companies = svc.crm_companies_migrate(
        source_companies=[{"id": "300", "xml_id": "co300", "responsible_id": "2", "custom_fields": {"30": "y"}}],
        target_companies=[{"id": "330", "xml_id": "co300"}],
    )
    assert contacts["migrated"] == 1
    assert companies["migrated"] == 1

    blocked_deal = svc.crm_deals_migrate(
        source_deals=[{"id": "400", "xml_id": "d400", "responsible_id": "1", "category_id": "10", "stage_id": "20", "company_id": "999"}],
        target_deals=[],
    )
    assert blocked_deal["blocked"] == 1

    ok_deal = svc.crm_deals_migrate(
        source_deals=[{"id": "401", "xml_id": "d401", "responsible_id": "1", "category_id": "10", "stage_id": "20", "company_id": "300", "contact_ids": ["200"], "custom_fields": {"30": "ok"}}],
        target_deals=[{"id": "440", "xml_id": "d401"}],
    )
    assert ok_deal["migrated"] == 1

    comments = svc.crm_comments_migrate([{"id": "500", "entity_type": "deal", "entity_id": "401", "author_id": "1", "body": "crm note"}])
    files = svc.crm_file_refs_migrate([{"id": "600", "owner_type": "deal", "owner_id": "401", "name": "deal.pdf"}])
    assert comments["migrated"] == 1
    assert files["migrated"] == 1

    report = svc.get_report(run_id=run.run_id)
    crm_counts = [r for r in report["verification_results"] if r.check_type == "verify:counts" and r.entity_type == "crm"][0]
    assert crm_counts.details["deals"] >= 2
    files_check = [r for r in report["verification_results"] if r.check_type == "verify:files"][0]
    assert files_check.status == "partial"
