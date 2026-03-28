from __future__ import annotations

from b24_migrator.domain.models import DependencyStep, DomainModuleStatus


class DomainRegistryService:
    """Declares domain migrator lifecycle capabilities and dependency graph."""

    def list_domains(self) -> list[DomainModuleStatus]:
        return [
            DomainModuleStatus("Users", "implemented", "implemented", "implemented", "implemented", "implemented", []),
            DomainModuleStatus("Groups/Projects", "implemented", "implemented", "partial", "partial", "planned", ["Users"]),
            DomainModuleStatus("Tasks", "implemented", "implemented", "partial", "partial", "planned", ["Users", "Groups/Projects"]),
            DomainModuleStatus("CRM", "implemented", "implemented", "partial", "partial", "planned", ["Users", "Schemas/Fields/Categories/Stages"]),
            DomainModuleStatus("Smart Processes", "implemented", "implemented", "partial", "partial", "planned", ["Users", "Schemas/Fields/Categories/Stages"]),
            DomainModuleStatus("Business Processes/Robots/Automation", "implemented", "implemented", "partial", "partial", "planned", ["Users", "Schemas/Fields/Categories/Stages"]),
            DomainModuleStatus("Comments", "implemented", "implemented", "partial", "partial", "planned", ["Tasks", "CRM", "Smart Processes"]),
            DomainModuleStatus("Files", "implemented", "implemented", "partial", "partial", "planned", ["Comments", "CRM", "Tasks"]),
            DomainModuleStatus("Reports", "implemented", "implemented", "planned", "planned", "planned", ["Users", "CRM", "Tasks"]),
            DomainModuleStatus("Webhooks/Integrations", "implemented", "implemented", "implemented", "implemented", "planned", ["Users"]),
        ]

    def execution_graph(self) -> list[DependencyStep]:
        return [
            DependencyStep(1, "users", []),
            DependencyStep(2, "groups/projects", ["users"]),
            DependencyStep(3, "schemas/custom fields/categories/stages", ["users", "groups/projects"]),
            DependencyStep(4, "BP/robots/automation schemas", ["schemas/custom fields/categories/stages"]),
            DependencyStep(5, "CRM/tasks/smart-process items", ["users", "groups/projects", "schemas/custom fields/categories/stages"]),
            DependencyStep(6, "comments", ["CRM/tasks/smart-process items"]),
            DependencyStep(7, "files", ["comments"]),
            DependencyStep(8, "reports", ["users", "CRM/tasks/smart-process items"]),
            DependencyStep(9, "verification", ["reports", "files"]),
            DependencyStep(10, "delta", ["verification"]),
            DependencyStep(11, "cutover", ["delta"]),
        ]
