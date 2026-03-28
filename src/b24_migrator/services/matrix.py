from __future__ import annotations

from b24_migrator.domain.models import MigrationMatrixEntry


class MigrationMatrixService:
    """Static support matrix for migration entities and enterprise readiness notes."""

    def list_entries(self) -> list[MigrationMatrixEntry]:
        base_mapping = "Canonical mapping layer (source_id/source_uid -> target_id/target_uid)"
        return [
            MigrationMatrixEntry("users", "implemented", "user.get/list", "user.get/list", [], "XML_ID/email/login/manual review", "counts+relations+integrity", "incremental match refresh", "preserve target users only", "Ambiguous identities require manual queue"),
            MigrationMatrixEntry("groups", "partial", "sonet_group.get", "sonet_group.create/update", ["users"], base_mapping, "counts+relations", "planned", "cleanup preview only", "Group roles depend on user_map"),
            MigrationMatrixEntry("projects", "partial", "sonet_group.get(project)", "sonet_group.create(project)", ["users", "groups"], base_mapping, "counts+relations", "planned", "cleanup preview only", "Project owners and scrum specifics vary by tenant"),
            MigrationMatrixEntry("tasks", "partial", "tasks.task.list/get", "tasks.task.add/update", ["users", "groups/projects"], base_mapping, "counts+relations+integrity", "planned", "cleanup preview only", "Task links must resolve assignee/responsible/group"),
            MigrationMatrixEntry("crm", "partial", "crm.*.list", "crm.*.add/update", ["users", "schemas/custom fields/categories/stages"], base_mapping, "counts+relations+integrity", "planned", "cleanup preview only", "Pipelines/stages must be remapped"),
            MigrationMatrixEntry("business_processes", "partial", "bizproc.workflow.template.list", "bizproc.workflow.template.add", ["users", "schemas/custom fields/categories/stages"], base_mapping, "relations+integrity", "planned", "cleanup preview only", "Template constants and users need resolution"),
            MigrationMatrixEntry("smart_processes", "partial", "crm.type.list + crm.item.list", "crm.type.add + crm.item.add", ["users", "schemas/custom fields/categories/stages"], base_mapping, "counts+relations+integrity", "planned", "cleanup preview only", "Type schema must be migrated before items"),
            MigrationMatrixEntry("comments", "partial", "task.commentitem.getlist + crm.timeline.comment.list", "comment/timeline APIs", ["tasks", "crm", "smart_processes"], base_mapping, "relations+integrity", "planned", "cleanup preview only", "Owner entity mapping prerequisite"),
            MigrationMatrixEntry("files", "partial", "disk.file.get/list", "disk.file.upload", ["comments", "crm", "tasks"], base_mapping, "files+integrity", "planned", "cleanup preview only", "Binary payload transport policy required"),
            MigrationMatrixEntry("reports", "planned", "report.*", "report.*", ["users", "crm", "tasks", "smart_processes"], base_mapping, "relations", "planned", "cleanup preview only", "API variance across plans"),
            MigrationMatrixEntry("robots", "partial", "crm.automation.trigger/robot.*", "crm.automation.trigger/robot.*", ["business_processes", "schemas/custom fields/categories/stages"], base_mapping, "relations+integrity", "planned", "cleanup preview only", "Actions depend on stage/category remap"),
            MigrationMatrixEntry("webhooks", "implemented", "event.bind/list", "event.bind/list", ["users"], base_mapping, "integrity", "planned", "cleanup preview only", "Secrets must be rotated post-cutover"),
            MigrationMatrixEntry("automation", "partial", "bizproc + crm.automation.*", "bizproc + crm.automation.*", ["business_processes", "robots"], base_mapping, "relations+integrity", "planned", "cleanup preview only", "Cross-module references are tenant-specific"),
        ]
