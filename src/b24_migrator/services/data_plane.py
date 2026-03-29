from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from b24_migrator.domain.models import MappingRecord, UserReviewItem
from b24_migrator.services.mapping import MappingService, UserResolutionService
from b24_migrator.storage.repositories import MappingRepository, UserReviewQueueRepository


class DataPlaneMigrationService:
    """End-to-end data-plane operations for users/groups/projects/tasks/comments/files."""

    def __init__(self) -> None:
        self._mapping = MappingService()
        self._users = UserResolutionService()

    def sync_users(self, session: Session, *, source_users: list[dict[str, Any]], target_users: list[dict[str, Any]]) -> dict[str, Any]:
        resolved = 0
        unmatched = 0
        ambiguous = 0
        for source_user in source_users:
            out = self._users.resolve_user(session, source_user=source_user, target_candidates=target_users)
            if isinstance(out, UserReviewItem):
                ambiguous += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type="users",
                    source_id=str(source_user["id"]),
                    source_uid=source_user.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="ambiguous",
                    resolution_strategy="manual_review_required",
                    verification_status="failed",
                    error_payload={"reason": "ambiguous_match"},
                )
                continue
            if out.status == "resolved":
                resolved += 1
            else:
                unmatched += 1
        return {
            "source_count": len(source_users),
            "target_count": len(target_users),
            "resolved": resolved,
            "unmatched": unmatched,
            "ambiguous": ambiguous,
        }

    def user_review(self, session: Session, *, source_id: str, target_id: str, target_uid: str | None = None, actor: str = "manual") -> MappingRecord:
        now = datetime.now(tz=timezone.utc)
        queue_repo = UserReviewQueueRepository(session)
        queue_repo.close_open_by_source(source_id=source_id)
        source_row = MappingRepository(session).get("users", source_id)
        return self._mapping.upsert_mapping(
            session,
            entity_type="users",
            source_id=source_id,
            source_uid=source_row.source_uid if source_row else None,
            target_id=target_id,
            target_uid=target_uid,
            status="resolved",
            resolution_strategy=f"manual_override:{actor}",
            verification_status="passed",
            payload={"source_id": source_id, "target_id": target_id, "reviewed_at": now.isoformat()},
        )

    def sync_groups_or_projects(
        self,
        session: Session,
        *,
        entity_type: str,
        source_entities: list[dict[str, Any]],
        target_entities: list[dict[str, Any]],
        user_map: dict[str, str],
    ) -> dict[str, Any]:
        if entity_type not in {"groups", "projects"}:
            raise ValueError("entity_type must be groups or projects")
        resolved = 0
        created = 0
        blocked = 0
        risk_notes: list[str] = []
        target_by_uid = {str(item.get("xml_id") or ""): item for item in target_entities if item.get("xml_id")}
        target_by_name = {str(item.get("name") or "").strip().lower(): item for item in target_entities if item.get("name")}

        for item in source_entities:
            source_id = str(item["id"])
            source_uid = item.get("xml_id")
            members = [str(m) for m in item.get("member_user_ids", [])]
            unresolved_members = [m for m in members if m not in user_map]
            if unresolved_members:
                blocked += 1
                risk_notes.append(f"{entity_type}:{source_id}:unresolved_users={','.join(unresolved_members)}")
                self._mapping.upsert_mapping(
                    session,
                    entity_type=entity_type,
                    source_id=source_id,
                    source_uid=source_uid,
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_user_mapping",
                    verification_status="failed",
                    error_payload={"unresolved_user_refs": unresolved_members},
                )
                continue

            target = target_by_uid.get(str(source_uid or "")) or target_by_name.get(str(item.get("name", "")).strip().lower())
            if target:
                if source_uid and target.get("xml_id") and source_uid != target["xml_id"]:
                    risk_notes.append(f"{entity_type}:{source_id}:uid_conflict_existing_target={target['id']}")
                target_id = str(target["id"])
                strategy = "match:xml_id" if source_uid and target.get("xml_id") == source_uid else "match:name"
                resolved += 1
            else:
                target_id = f"created:{entity_type}:{source_id}"
                strategy = "create_on_target"
                created += 1
            self._mapping.upsert_mapping(
                session,
                entity_type=entity_type,
                source_id=source_id,
                source_uid=source_uid,
                target_id=target_id,
                target_uid=target.get("xml_id") if target else source_uid,
                status="resolved",
                resolution_strategy=strategy,
                verification_status="pending",
                payload={"member_target_user_ids": [user_map[m] for m in members]},
            )
        return {"resolved": resolved, "created": created, "blocked": blocked, "risk_notes": risk_notes}

    def migrate_tasks(self, session: Session, *, source_tasks: list[dict[str, Any]]) -> dict[str, Any]:
        user_map = self._mapping_by_source(session, "users")
        group_map = self._mapping_by_source(session, "groups")
        project_map = self._mapping_by_source(session, "projects")
        migrated = 0
        blocked = 0
        for task in source_tasks:
            src_id = str(task["id"])
            missing_refs = self._missing_task_refs(task, user_map, group_map, project_map)
            if missing_refs:
                blocked += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type="tasks",
                    source_id=src_id,
                    source_uid=task.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_unresolved_dependency",
                    verification_status="failed",
                    linked_parent_type="groups/projects",
                    linked_parent_source_id=str(task.get("group_id") or task.get("project_id") or ""),
                    linked_parent_target_id=None,
                    error_payload={"missing_refs": missing_refs},
                )
                continue
            target_id = str(task.get("target_id") or f"created:task:{src_id}")
            migrated += 1
            self._mapping.upsert_mapping(
                session,
                entity_type="tasks",
                source_id=src_id,
                source_uid=task.get("xml_id"),
                target_id=target_id,
                target_uid=task.get("xml_id"),
                status="resolved",
                resolution_strategy="create_or_update",
                verification_status="pending",
                linked_parent_type="groups/projects",
                linked_parent_source_id=str(task.get("group_id") or task.get("project_id") or ""),
                linked_parent_target_id=group_map.get(str(task.get("group_id"))) or project_map.get(str(task.get("project_id"))),
                payload={
                    "author_target_id": user_map.get(str(task.get("author_id"))),
                    "responsible_target_id": user_map.get(str(task.get("responsible_id"))),
                    "accomplice_target_ids": [user_map[str(v)] for v in task.get("accomplice_ids", [])],
                    "auditor_target_ids": [user_map[str(v)] for v in task.get("auditor_ids", [])],
                    "status": task.get("status"),
                    "priority": task.get("priority"),
                    "deadline": task.get("deadline"),
                    "timestamps": {"created_at": task.get("created_at"), "updated_at": task.get("updated_at")},
                },
            )
        return {"migrated": migrated, "blocked": blocked}

    def migrate_comments(self, session: Session, *, source_comments: list[dict[str, Any]]) -> dict[str, Any]:
        user_map = self._mapping_by_source(session, "users")
        task_map = self._mapping_by_source(session, "tasks")
        migrated = 0
        blocked = 0
        for comment in source_comments:
            src_id = str(comment["id"])
            source_task_id = str(comment.get("task_id"))
            source_author = str(comment.get("author_id"))
            if source_task_id not in task_map or source_author not in user_map:
                blocked += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type="comments",
                    source_id=src_id,
                    source_uid=comment.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_unresolved_dependency",
                    verification_status="failed",
                    linked_parent_type="tasks",
                    linked_parent_source_id=source_task_id,
                    linked_parent_target_id=task_map.get(source_task_id),
                    error_payload={"missing_task": source_task_id not in task_map, "missing_author": source_author not in user_map},
                )
                continue
            migrated += 1
            self._mapping.upsert_mapping(
                session,
                entity_type="comments",
                source_id=src_id,
                source_uid=comment.get("xml_id"),
                target_id=str(comment.get("target_id") or f"created:comment:{src_id}"),
                target_uid=comment.get("xml_id"),
                status="resolved",
                resolution_strategy="create_or_update",
                verification_status="pending",
                linked_parent_type="tasks",
                linked_parent_source_id=source_task_id,
                linked_parent_target_id=task_map[source_task_id],
                payload={"author_target_id": user_map[source_author], "body": comment.get("body"), "timestamp": comment.get("created_at")},
            )
        return {"migrated": migrated, "blocked": blocked}

    def migrate_file_refs(self, session: Session, *, source_refs: list[dict[str, Any]]) -> dict[str, Any]:
        task_map = self._mapping_by_source(session, "tasks")
        migrated = 0
        blocked = 0
        for ref in source_refs:
            src_id = str(ref["id"])
            source_task_id = str(ref.get("task_id"))
            if source_task_id not in task_map:
                blocked += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type="file_refs",
                    source_id=src_id,
                    source_uid=ref.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_unresolved_dependency",
                    verification_status="failed",
                    linked_parent_type="tasks",
                    linked_parent_source_id=source_task_id,
                    linked_parent_target_id=None,
                    error_payload={"missing_task_mapping": source_task_id},
                )
                continue
            migrated += 1
            self._mapping.upsert_mapping(
                session,
                entity_type="file_refs",
                source_id=src_id,
                source_uid=ref.get("xml_id"),
                target_id=str(ref.get("target_id") or f"ref:{src_id}"),
                target_uid=ref.get("external_id"),
                status="resolved",
                resolution_strategy="metadata_reference_only",
                verification_status="partial",
                linked_parent_type="tasks",
                linked_parent_source_id=source_task_id,
                linked_parent_target_id=task_map[source_task_id],
                payload={
                    "name": ref.get("name"),
                    "size": ref.get("size"),
                    "mime": ref.get("mime"),
                    "payload_copy_status": "planned",
                },
            )
        return {"migrated": migrated, "blocked": blocked, "payload_copy": "partial_planned"}

    @staticmethod
    def _mapping_by_source(session: Session, entity_type: str) -> dict[str, str]:
        rows = MappingRepository(session).list_all(entity_type=entity_type, status="resolved", limit=50000)
        return {row.source_id: row.target_id for row in rows if row.target_id}

    @staticmethod
    def _missing_task_refs(task: dict[str, Any], user_map: dict[str, str], group_map: dict[str, str], project_map: dict[str, str]) -> dict[str, Any]:
        missing: dict[str, Any] = {}
        user_refs = {
            "author_id": task.get("author_id"),
            "responsible_id": task.get("responsible_id"),
        }
        for key, value in user_refs.items():
            if value is not None and str(value) not in user_map:
                missing[key] = str(value)
        for key in ("accomplice_ids", "auditor_ids"):
            unresolved = [str(v) for v in task.get(key, []) if str(v) not in user_map]
            if unresolved:
                missing[key] = unresolved
        if task.get("group_id") is not None and str(task["group_id"]) not in group_map:
            missing["group_id"] = str(task["group_id"])
        if task.get("project_id") is not None and str(task["project_id"]) not in project_map:
            missing["project_id"] = str(task["project_id"])
        return missing
