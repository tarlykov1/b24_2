from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from b24_migrator.domain.models import Plan


class PlannerService:
    """Builds deterministic migration plans from job context and scope."""

    def create_plan(self, source_portal: str, target_portal: str, scope: list[str], job_id: str) -> Plan:
        ordered_scope = sorted(scope)
        stable_payload = {
            "job_id": job_id,
            "source": source_portal,
            "target": target_portal,
            "scope": ordered_scope,
        }
        serialized = json.dumps(stable_payload, sort_keys=True, separators=(",", ":"))
        deterministic_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        plan_id = str(uuid5(NAMESPACE_URL, deterministic_hash))
        return Plan(
            plan_id=plan_id,
            job_id=job_id,
            source_portal=source_portal,
            target_portal=target_portal,
            scope=ordered_scope,
            deterministic_hash=deterministic_hash,
            created_at=datetime.now(tz=timezone.utc),
        )
