from __future__ import annotations

from dataclasses import asdict

from b24_migrator.domain.models import DependencyStep, MappingRecord


class CutoverService:
    """Planning helpers for target inspection, cleanup, delta and cutover readiness."""

    def target_inspection(self, mappings: list[MappingRecord]) -> dict[str, object]:
        unresolved = [m for m in mappings if m.status in {"unmatched", "error"}]
        return {
            "mapped_total": len(mappings),
            "unresolved_total": len(unresolved),
            "unresolved_entities": sorted({m.entity_type for m in unresolved}),
            "preserve_users_policy": True,
        }

    def cleanup_plan(self, mappings: list[MappingRecord], dry_run: bool = True) -> dict[str, object]:
        entities = sorted({m.entity_type for m in mappings if m.entity_type != "users"})
        return {
            "dry_run": dry_run,
            "destructive_allowed": False,
            "actions": [{"entity": e, "mode": "preview-delete-imported-only"} for e in entities],
            "preserve_users_policy": True,
        }

    def cleanup_execute(self, cleanup_plan_payload: dict[str, object], dry_run: bool = True) -> dict[str, object]:
        if not dry_run and cleanup_plan_payload.get("destructive_allowed") is False:
            return {"status": "blocked", "reason": "unsafe_cleanup_without_explicit_override", "dry_run": dry_run}
        return {"status": "previewed" if dry_run else "executed", "dry_run": dry_run, "plan": cleanup_plan_payload}

    def delta_plan(self, graph: list[DependencyStep]) -> dict[str, object]:
        return {"resume_supported": True, "steps": [asdict(step) for step in graph], "strategy": "checkpoint-driven-delta"}

    def delta_execute(self, plan_id: str) -> dict[str, object]:
        return {"plan_id": plan_id, "status": "queued", "mode": "delta"}

    def cutover_readiness(self, inspection: dict[str, object], verification_summary: dict[str, object]) -> dict[str, object]:
        ready = inspection.get("unresolved_total", 1) == 0 and verification_summary.get("all_passed", False)
        return {
            "ready": ready,
            "blocking_issues": [] if ready else ["unresolved_mappings_or_failed_verification"],
            "preserve_users_policy": True,
        }
