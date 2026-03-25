from datetime import datetime, timezone

from b24_migrator.domain.models import MigrationPlan
from b24_migrator.domain.status import RunStatus
from b24_migrator.services.executor import ExecutionService


def _plan() -> MigrationPlan:
    return MigrationPlan(
        plan_id="plan-1",
        job_id="job-1",
        source_portal="https://source",
        target_portal="https://target",
        scope=["crm", "tasks"],
        deterministic_hash="hash",
        created_at=datetime.now(tz=timezone.utc),
    )


def test_execute_dry_run_returns_paused() -> None:
    service = ExecutionService()

    result = service.execute(plan=_plan(), dry_run=True)

    assert result.status == RunStatus.PAUSED
    assert result.checkpoint_token == "dry-run:0"


def test_execute_non_dry_run_completes() -> None:
    service = ExecutionService()

    result = service.execute(plan=_plan(), dry_run=False)

    assert result.status == RunStatus.COMPLETED
    assert result.processed_items == 2
