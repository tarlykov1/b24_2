from __future__ import annotations

from uuid import uuid4

from b24_migrator.domain.models import ExecutionResult, MigrationPlan
from b24_migrator.domain.status import RunStatus


class ExecutionService:
    """Executes or resumes migration runs in deterministic chunks."""

    def execute(self, plan: MigrationPlan, dry_run: bool, resume_from: ExecutionResult | None = None) -> ExecutionResult:
        run_id = resume_from.run_id if resume_from else str(uuid4())
        base_count = resume_from.processed_items if resume_from else 0

        if dry_run:
            return ExecutionResult(
                plan_id=plan.plan_id,
                run_id=run_id,
                status=RunStatus.PAUSED,
                processed_items=base_count,
                checkpoint_token=resume_from.checkpoint_token if resume_from else "dry-run:0",
            )

        next_count = base_count + max(len(plan.scope), 1)
        checkpoint = f"offset:{next_count}"
        return ExecutionResult(
            plan_id=plan.plan_id,
            run_id=run_id,
            status=RunStatus.COMPLETED,
            processed_items=next_count,
            checkpoint_token=checkpoint,
        )
