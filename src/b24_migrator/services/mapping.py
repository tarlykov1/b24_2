from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from b24_migrator.domain.models import MappingRecord, UserReviewItem
from b24_migrator.storage.repositories import MappingRepository, UserReviewQueueRepository


class MappingService:
    """Canonical mapping operations shared by all migration domains."""

    def upsert_mapping(
        self,
        session: Session,
        *,
        entity_type: str,
        source_id: str,
        source_uid: str | None,
        target_id: str | None,
        target_uid: str | None,
        status: str,
        resolution_strategy: str,
        verification_status: str = "pending",
        linked_parent_type: str | None = None,
        linked_parent_source_id: str | None = None,
        linked_parent_target_id: str | None = None,
        payload: dict[str, Any] | None = None,
        error_payload: dict[str, Any] | None = None,
    ) -> MappingRecord:
        now = datetime.now(tz=timezone.utc)
        existing = MappingRepository(session).get(entity_type, source_id)
        payload_hash = hashlib.sha256(str(payload).encode("utf-8")).hexdigest() if payload is not None else None
        mapping = MappingRecord(
            mapping_id=existing.mapping_id if existing else None,
            entity_type=entity_type,
            source_id=source_id,
            source_uid=source_uid,
            target_id=target_id,
            target_uid=target_uid,
            status=status,
            resolution_strategy=resolution_strategy,
            verification_status=verification_status,
            linked_parent_type=linked_parent_type,
            linked_parent_source_id=linked_parent_source_id,
            linked_parent_target_id=linked_parent_target_id,
            payload_hash=payload_hash,
            error_payload=error_payload,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        MappingRepository(session).upsert(mapping)
        return mapping


class UserResolutionService:
    """User mapping policy with preserve-target-users rule and conflict queue."""

    matching_priority = ("xml_id", "email", "login")

    def resolve_user(
        self,
        session: Session,
        *,
        source_user: dict[str, Any],
        target_candidates: list[dict[str, Any]],
    ) -> MappingRecord | UserReviewItem:
        scored: list[tuple[str, dict[str, Any]]] = []
        for key in self.matching_priority:
            source_value = str(source_user.get(key, "")).strip().lower()
            if not source_value:
                continue
            matches = [c for c in target_candidates if str(c.get(key, "")).strip().lower() == source_value]
            if len(matches) == 1:
                if scored:
                    break
                target = matches[0]
                return MappingService().upsert_mapping(
                    session,
                    entity_type="users",
                    source_id=str(source_user["id"]),
                    source_uid=source_user.get("xml_id"),
                    target_id=str(target["id"]),
                    target_uid=target.get("xml_id"),
                    status="resolved",
                    resolution_strategy=f"match:{key}",
                    verification_status="pending",
                    payload={"source": source_user, "target": target},
                )
            if len(matches) > 1:
                scored = [(key, m) for m in matches]
                break

        if scored:
            now = datetime.now(tz=timezone.utc)
            review = UserReviewItem(
                review_id=None,
                source_id=str(source_user["id"]),
                source_uid=source_user.get("xml_id"),
                candidates=[{"strategy": s, "candidate": m} for s, m in scored],
                reason="ambiguous_match",
                status="open",
                created_at=now,
                updated_at=now,
            )
            UserReviewQueueRepository(session).save(review)
            return review

        return MappingService().upsert_mapping(
            session,
            entity_type="users",
            source_id=str(source_user["id"]),
            source_uid=source_user.get("xml_id"),
            target_id=None,
            target_uid=None,
            status="unmatched",
            resolution_strategy="manual_review_required",
            verification_status="failed",
            error_payload={"reason": "no_match", "source": source_user},
        )
