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

    def sync_crm_dictionaries(
        self,
        session: Session,
        *,
        source_categories: list[dict[str, Any]],
        target_categories: list[dict[str, Any]],
        source_stages: list[dict[str, Any]],
        target_stages: list[dict[str, Any]],
        source_custom_fields: list[dict[str, Any]],
        target_custom_fields: list[dict[str, Any]],
    ) -> dict[str, Any]:
        categories = self._sync_dictionary(session, entity_type="crm_categories", source_rows=source_categories, target_rows=target_categories)
        stages = self._sync_dictionary(session, entity_type="crm_stages", source_rows=source_stages, target_rows=target_stages)

        implemented_types = {"string", "double", "integer", "boolean", "date", "datetime", "enumeration"}
        partial_types = {"crm", "employee", "money", "url"}
        target_by_code = {str(row.get("code") or ""): row for row in target_custom_fields if row.get("code")}
        custom_fields_result = {"implemented": 0, "partial": 0, "unsupported": 0, "resolved": 0, "created": 0}
        for field in source_custom_fields:
            src_id = str(field["id"])
            code = str(field.get("code") or "")
            field_type = str(field.get("type") or "").lower()
            target = target_by_code.get(code)
            if field_type in implemented_types:
                support = "implemented"
            elif field_type in partial_types:
                support = "partial"
            else:
                support = "unsupported"
            custom_fields_result[support] += 1
            if support == "unsupported":
                self._mapping.upsert_mapping(
                    session,
                    entity_type="crm_custom_fields",
                    source_id=src_id,
                    source_uid=code,
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="unsupported_field_type",
                    verification_status="failed",
                    error_payload={"field_type": field_type, "support_status": support},
                )
                continue
            target_id = str(target["id"]) if target else f"created:crm_custom_field:{src_id}"
            custom_fields_result["resolved" if target else "created"] += 1
            self._mapping.upsert_mapping(
                session,
                entity_type="crm_custom_fields",
                source_id=src_id,
                source_uid=code,
                target_id=target_id,
                target_uid=code if target else field.get("code"),
                status="resolved",
                resolution_strategy="match:code" if target else "create_on_target",
                verification_status="partial" if support == "partial" else "pending",
                payload={"field_type": field_type, "support_status": support},
            )
        return {"categories": categories, "stages": stages, "custom_fields": custom_fields_result}

    def migrate_crm_contacts(self, session: Session, *, source_contacts: list[dict[str, Any]], target_contacts: list[dict[str, Any]]) -> dict[str, Any]:
        user_map = self._mapping_by_source(session, "users")
        stage_map = self._mapping_by_source(session, "crm_stages")
        category_map = self._mapping_by_source(session, "crm_categories")
        field_map = self._mapping_by_source(session, "crm_custom_fields")
        target_by_uid = {str(item.get("xml_id") or ""): item for item in target_contacts if item.get("xml_id")}
        return self._migrate_crm_entities(
            session,
            entity_type="crm_contacts",
            source_entities=source_contacts,
            user_map=user_map,
            stage_map=stage_map,
            category_map=category_map,
            field_map=field_map,
            target_by_uid=target_by_uid,
        )

    def migrate_crm_companies(self, session: Session, *, source_companies: list[dict[str, Any]], target_companies: list[dict[str, Any]]) -> dict[str, Any]:
        user_map = self._mapping_by_source(session, "users")
        stage_map = self._mapping_by_source(session, "crm_stages")
        category_map = self._mapping_by_source(session, "crm_categories")
        field_map = self._mapping_by_source(session, "crm_custom_fields")
        target_by_uid = {str(item.get("xml_id") or ""): item for item in target_companies if item.get("xml_id")}
        return self._migrate_crm_entities(
            session,
            entity_type="crm_companies",
            source_entities=source_companies,
            user_map=user_map,
            stage_map=stage_map,
            category_map=category_map,
            field_map=field_map,
            target_by_uid=target_by_uid,
        )

    def migrate_crm_deals(self, session: Session, *, source_deals: list[dict[str, Any]], target_deals: list[dict[str, Any]]) -> dict[str, Any]:
        user_map = self._mapping_by_source(session, "users")
        stage_map = self._mapping_by_source(session, "crm_stages")
        category_map = self._mapping_by_source(session, "crm_categories")
        field_map = self._mapping_by_source(session, "crm_custom_fields")
        company_map = self._mapping_by_source(session, "crm_companies")
        contact_map = self._mapping_by_source(session, "crm_contacts")
        target_by_uid = {str(item.get("xml_id") or ""): item for item in target_deals if item.get("xml_id")}
        migrated = 0
        blocked = 0
        for deal in source_deals:
            source_id = str(deal["id"])
            missing_refs = self._missing_crm_refs(
                deal,
                user_map=user_map,
                stage_map=stage_map,
                category_map=category_map,
                field_map=field_map,
                require_category=True,
                require_stage=True,
            )
            company_id = deal.get("company_id")
            if company_id is not None and str(company_id) not in company_map:
                missing_refs["company_id"] = str(company_id)
            unresolved_contacts = [str(cid) for cid in deal.get("contact_ids", []) if str(cid) not in contact_map]
            if unresolved_contacts:
                missing_refs["contact_ids"] = unresolved_contacts
            if missing_refs:
                blocked += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type="crm_deals",
                    source_id=source_id,
                    source_uid=deal.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_unresolved_dependency",
                    verification_status="failed",
                    linked_parent_type="crm_companies/crm_contacts",
                    linked_parent_source_id=str(company_id or ""),
                    linked_parent_target_id=company_map.get(str(company_id or "")),
                    error_payload={"missing_refs": missing_refs},
                )
                continue
            target = target_by_uid.get(str(deal.get("xml_id") or ""))
            target_id = str(target["id"]) if target else f"created:crm_deal:{source_id}"
            migrated += 1
            self._mapping.upsert_mapping(
                session,
                entity_type="crm_deals",
                source_id=source_id,
                source_uid=deal.get("xml_id"),
                target_id=target_id,
                target_uid=target.get("xml_id") if target else deal.get("xml_id"),
                status="resolved",
                resolution_strategy="match:xml_id" if target else "create_on_target",
                verification_status="pending",
                linked_parent_type="crm_companies",
                linked_parent_source_id=str(company_id or ""),
                linked_parent_target_id=company_map.get(str(company_id or "")),
                payload={
                    "responsible_target_user_id": user_map.get(str(deal.get("responsible_id"))),
                    "category_target_id": category_map.get(str(deal.get("category_id"))),
                    "stage_target_id": stage_map.get(str(deal.get("stage_id"))),
                    "company_target_id": company_map.get(str(company_id)) if company_id is not None else None,
                    "contact_target_ids": [contact_map[str(cid)] for cid in deal.get("contact_ids", [])],
                    "custom_field_bindings": self._bind_custom_fields(deal.get("custom_fields", {}), field_map),
                },
            )
        return {"migrated": migrated, "blocked": blocked}

    def migrate_crm_comments(self, session: Session, *, source_comments: list[dict[str, Any]]) -> dict[str, Any]:
        user_map = self._mapping_by_source(session, "users")
        entity_maps = {
            "deal": self._mapping_by_source(session, "crm_deals"),
            "company": self._mapping_by_source(session, "crm_companies"),
            "contact": self._mapping_by_source(session, "crm_contacts"),
        }
        migrated = 0
        blocked = 0
        for comment in source_comments:
            src_id = str(comment["id"])
            entity_type = str(comment.get("entity_type") or "").lower()
            entity_source_id = str(comment.get("entity_id") or "")
            author_id = str(comment.get("author_id") or "")
            parent_map = entity_maps.get(entity_type, {})
            if entity_source_id not in parent_map or author_id not in user_map:
                blocked += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type="crm_comments",
                    source_id=src_id,
                    source_uid=comment.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_unresolved_dependency",
                    verification_status="failed",
                    linked_parent_type=f"crm_{entity_type}",
                    linked_parent_source_id=entity_source_id,
                    linked_parent_target_id=parent_map.get(entity_source_id),
                    error_payload={"missing_entity": entity_source_id not in parent_map, "missing_author": author_id not in user_map},
                )
                continue
            migrated += 1
            self._mapping.upsert_mapping(
                session,
                entity_type="crm_comments",
                source_id=src_id,
                source_uid=comment.get("xml_id"),
                target_id=str(comment.get("target_id") or f"created:crm_comment:{src_id}"),
                target_uid=comment.get("xml_id"),
                status="resolved",
                resolution_strategy="create_or_update",
                verification_status="pending",
                linked_parent_type=f"crm_{entity_type}",
                linked_parent_source_id=entity_source_id,
                linked_parent_target_id=parent_map[entity_source_id],
                payload={"author_target_id": user_map[author_id], "body": comment.get("body"), "timestamps": {"created_at": comment.get("created_at"), "updated_at": comment.get("updated_at")}},
            )
        return {"migrated": migrated, "blocked": blocked}

    def migrate_crm_file_refs(self, session: Session, *, source_refs: list[dict[str, Any]]) -> dict[str, Any]:
        entity_maps = {
            "deal": self._mapping_by_source(session, "crm_deals"),
            "company": self._mapping_by_source(session, "crm_companies"),
            "contact": self._mapping_by_source(session, "crm_contacts"),
        }
        migrated = 0
        blocked = 0
        for ref in source_refs:
            src_id = str(ref["id"])
            owner_type = str(ref.get("owner_type") or "").lower()
            owner_source_id = str(ref.get("owner_id") or "")
            parent_map = entity_maps.get(owner_type, {})
            if owner_source_id not in parent_map:
                blocked += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type="crm_file_refs",
                    source_id=src_id,
                    source_uid=ref.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_unresolved_dependency",
                    verification_status="failed",
                    linked_parent_type=f"crm_{owner_type}",
                    linked_parent_source_id=owner_source_id,
                    linked_parent_target_id=None,
                    error_payload={"missing_owner_mapping": owner_source_id, "owner_type": owner_type},
                )
                continue
            migrated += 1
            self._mapping.upsert_mapping(
                session,
                entity_type="crm_file_refs",
                source_id=src_id,
                source_uid=ref.get("xml_id"),
                target_id=str(ref.get("target_id") or f"crm_ref:{src_id}"),
                target_uid=ref.get("external_id"),
                status="resolved",
                resolution_strategy="metadata_reference_only",
                verification_status="partial",
                linked_parent_type=f"crm_{owner_type}",
                linked_parent_source_id=owner_source_id,
                linked_parent_target_id=parent_map[owner_source_id],
                payload={
                    "name": ref.get("name"),
                    "size": ref.get("size"),
                    "mime": ref.get("mime"),
                    "storage_id": ref.get("storage_id"),
                    "payload_copy_status": "planned",
                },
            )
        return {"migrated": migrated, "blocked": blocked, "payload_copy": "partial_planned"}

    def _sync_dictionary(self, session: Session, *, entity_type: str, source_rows: list[dict[str, Any]], target_rows: list[dict[str, Any]]) -> dict[str, int]:
        target_by_uid = {str(row.get("xml_id") or row.get("code") or ""): row for row in target_rows if row.get("xml_id") or row.get("code")}
        target_by_name = {str(row.get("name") or "").strip().lower(): row for row in target_rows if row.get("name")}
        resolved = 0
        created = 0
        for row in source_rows:
            source_id = str(row["id"])
            source_uid = row.get("xml_id") or row.get("code")
            target = target_by_uid.get(str(source_uid or "")) or target_by_name.get(str(row.get("name") or "").strip().lower())
            if target:
                resolved += 1
                target_id = str(target["id"])
                strategy = "match:uid" if source_uid and str(target.get("xml_id") or target.get("code") or "") == str(source_uid) else "match:name"
            else:
                created += 1
                target_id = f"created:{entity_type}:{source_id}"
                strategy = "create_on_target"
            self._mapping.upsert_mapping(
                session,
                entity_type=entity_type,
                source_id=source_id,
                source_uid=str(source_uid) if source_uid is not None else None,
                target_id=target_id,
                target_uid=str(target.get("xml_id") or target.get("code")) if target else str(source_uid or ""),
                status="resolved",
                resolution_strategy=strategy,
                verification_status="pending",
            )
        return {"resolved": resolved, "created": created}

    def _migrate_crm_entities(
        self,
        session: Session,
        *,
        entity_type: str,
        source_entities: list[dict[str, Any]],
        user_map: dict[str, str],
        stage_map: dict[str, str],
        category_map: dict[str, str],
        field_map: dict[str, str],
        target_by_uid: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        migrated = 0
        blocked = 0
        for row in source_entities:
            source_id = str(row["id"])
            missing_refs = self._missing_crm_refs(row, user_map=user_map, stage_map=stage_map, category_map=category_map, field_map=field_map, require_category=False, require_stage=False)
            if missing_refs:
                blocked += 1
                self._mapping.upsert_mapping(
                    session,
                    entity_type=entity_type,
                    source_id=source_id,
                    source_uid=row.get("xml_id"),
                    target_id=None,
                    target_uid=None,
                    status="error",
                    resolution_strategy="blocked_by_unresolved_dependency",
                    verification_status="failed",
                    error_payload={"missing_refs": missing_refs},
                )
                continue
            target = target_by_uid.get(str(row.get("xml_id") or ""))
            target_id = str(target["id"]) if target else f"created:{entity_type}:{source_id}"
            migrated += 1
            self._mapping.upsert_mapping(
                session,
                entity_type=entity_type,
                source_id=source_id,
                source_uid=row.get("xml_id"),
                target_id=target_id,
                target_uid=target.get("xml_id") if target else row.get("xml_id"),
                status="resolved",
                resolution_strategy="match:xml_id" if target else "create_on_target",
                verification_status="pending",
                payload={
                    "responsible_target_user_id": user_map.get(str(row.get("responsible_id"))),
                    "category_target_id": category_map.get(str(row.get("category_id"))) if row.get("category_id") is not None else None,
                    "stage_target_id": stage_map.get(str(row.get("stage_id"))) if row.get("stage_id") is not None else None,
                    "custom_field_bindings": self._bind_custom_fields(row.get("custom_fields", {}), field_map),
                },
            )
        return {"migrated": migrated, "blocked": blocked}

    @staticmethod
    def _bind_custom_fields(source_bindings: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
        return {field_map[str(k)]: v for k, v in source_bindings.items() if str(k) in field_map}

    @staticmethod
    def _missing_crm_refs(
        row: dict[str, Any],
        *,
        user_map: dict[str, str],
        stage_map: dict[str, str],
        category_map: dict[str, str],
        field_map: dict[str, str],
        require_category: bool,
        require_stage: bool,
    ) -> dict[str, Any]:
        missing: dict[str, Any] = {}
        responsible_id = row.get("responsible_id")
        if responsible_id is not None and str(responsible_id) not in user_map:
            missing["responsible_id"] = str(responsible_id)
        category_id = row.get("category_id")
        if require_category and category_id is not None and str(category_id) not in category_map:
            missing["category_id"] = str(category_id)
        stage_id = row.get("stage_id")
        if require_stage and stage_id is not None and str(stage_id) not in stage_map:
            missing["stage_id"] = str(stage_id)
        unresolved_fields = [str(k) for k in row.get("custom_fields", {}).keys() if str(k) not in field_map]
        if unresolved_fields:
            missing["custom_field_ids"] = unresolved_fields
        return missing

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
