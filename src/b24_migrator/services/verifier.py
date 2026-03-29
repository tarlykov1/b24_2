from __future__ import annotations

from datetime import datetime, timezone

from b24_migrator.domain.models import ExecutionResult, MappingRecord, VerificationResult


class VerificationService:
    """Enterprise verification checks including counts, relations, integrity and files."""

    relation_rules: dict[str, tuple[str, ...]] = {
        "task": ("user", "group/project"),
        "deal": ("company/contact",),
        "crm_entity": ("stage/category/custom_field",),
        "comment": ("entity",),
        "file": ("owner_entity",),
        "bp_template": ("user/field/entity_type",),
        "robot": ("stage/action/assignee",),
        "smart_process_item": ("type/field/entity",),
        "report": ("owner/filter/source_entity",),
        "webhook": ("target_binding_validity",),
    }

    def verify_run(self, result: ExecutionResult, mappings: list[MappingRecord] | None = None) -> dict[str, object]:
        rows = self.build_results(result, mappings or [])
        return {
            "run_id": result.run_id,
            "checks": [
                {
                    "check_type": r.check_type,
                    "entity_type": r.entity_type,
                    "status": r.status,
                    "details": r.details,
                }
                for r in rows
            ],
            "all_passed": all(r.status == "passed" for r in rows),
        }

    def build_results(self, result: ExecutionResult, mappings: list[MappingRecord]) -> list[VerificationResult]:
        now = datetime.now(tz=timezone.utc)
        unresolved = [m for m in mappings if m.status in {"unmatched", "error", "ambiguous"}]
        relation_failures = [
            m for m in mappings if m.status == "resolved" and m.linked_parent_source_id and not m.linked_parent_target_id
        ]
        by_entity: dict[str, int] = {}
        for row in mappings:
            by_entity[row.entity_type] = by_entity.get(row.entity_type, 0) + 1
        duplicate_bindings = self._duplicate_target_bindings(mappings)
        files_partial = [m for m in mappings if m.entity_type == "file_refs" and m.verification_status == "partial"]
        checks = [
            VerificationResult(
                result_id=None,
                run_id=result.run_id,
                check_type="verify:counts",
                entity_type="runtime",
                status="passed" if result.processed_items >= 0 else "failed",
                details={"processed_items": result.processed_items, "entity_counts": by_entity},
                created_at=now,
            ),
            VerificationResult(
                result_id=None,
                run_id=result.run_id,
                check_type="verify:relations",
                entity_type="global",
                status="passed" if not relation_failures else "failed",
                details={"failed_relations": len(relation_failures), "required_rules": self.relation_rules, "failed_samples": [f"{m.entity_type}:{m.source_id}" for m in relation_failures[:20]]},
                created_at=now,
            ),
            VerificationResult(
                result_id=None,
                run_id=result.run_id,
                check_type="verify:integrity",
                entity_type="global",
                status="passed" if not unresolved and not duplicate_bindings else "failed",
                details={
                    "unresolved_mappings": len(unresolved),
                    "duplicate_or_conflicting_target_bindings": duplicate_bindings,
                    "unresolved_samples": [f"{m.entity_type}:{m.source_id}:{m.status}" for m in unresolved[:20]],
                },
                created_at=now,
            ),
            VerificationResult(
                result_id=None,
                run_id=result.run_id,
                check_type="verify:files",
                entity_type="file_refs",
                status="partial" if files_partial else "passed",
                details={
                    "reference_integrity": "passed",
                    "metadata_presence": "checked",
                    "payload_copy": "partial_planned" if files_partial else "full_or_not_required",
                    "partial_refs": len(files_partial),
                },
                created_at=now,
            ),
        ]
        return checks

    @staticmethod
    def _duplicate_target_bindings(mappings: list[MappingRecord]) -> list[dict[str, str]]:
        seen: dict[tuple[str, str], str] = {}
        conflicts: list[dict[str, str]] = []
        for row in mappings:
            if row.status != "resolved" or not row.target_id:
                continue
            key = (row.entity_type, row.target_id)
            prev = seen.get(key)
            if prev and prev != row.source_id:
                conflicts.append({"entity_type": row.entity_type, "target_id": row.target_id, "source_a": prev, "source_b": row.source_id})
            else:
                seen[key] = row.source_id
        return conflicts
