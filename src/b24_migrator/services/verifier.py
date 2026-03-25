from __future__ import annotations

from b24_migrator.domain.models import ExecutionResult


class VerificationService:
    """Verifies migrated runtime state consistency for automation gates."""

    def verify_run(self, result: ExecutionResult) -> dict[str, object]:
        checks = {
            "has_run_id": bool(result.run_id),
            "has_plan_id": bool(result.plan_id),
            "processed_non_negative": result.processed_items >= 0,
        }
        checks["all_passed"] = all(checks.values())
        return checks
