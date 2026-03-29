from __future__ import annotations

from b24_migrator.domain.models import DependencyStep, DomainModuleStatus


class DomainRegistryService:
    """Declares domain migrator lifecycle capabilities and dependency graph."""

    def list_domains(self) -> list[DomainModuleStatus]:
        return [
            DomainModuleStatus("Users", "implemented", "implemented", "implemented", "implemented", "implemented", []),
            DomainModuleStatus("Groups/Projects", "implemented", "implemented", "implemented", "implemented", "planned", ["Users"]),
            DomainModuleStatus("Tasks", "implemented", "implemented", "implemented", "implemented", "planned", ["Users", "Groups/Projects"]),
            DomainModuleStatus("CRM", "implemented", "implemented", "partial", "partial", "planned", ["Users", "Schemas/Fields/Categories/Stages"]),
            DomainModuleStatus("Smart Processes", "implemented", "implemented", "partial", "partial", "planned", ["Users", "Schemas/Fields/Categories/Stages"]),
            DomainModuleStatus("Business Processes/Robots/Automation", "implemented", "implemented", "partial", "partial", "planned", ["Users", "Schemas/Fields/Categories/Stages"]),
            DomainModuleStatus("Comments", "implemented", "implemented", "implemented", "implemented", "planned", ["Tasks", "CRM", "Smart Processes"]),
            DomainModuleStatus("Files", "implemented", "implemented", "partial", "implemented", "planned", ["Comments", "CRM", "Tasks"]),
            DomainModuleStatus("Reports", "implemented", "implemented", "planned", "planned", "planned", ["Users", "CRM", "Tasks"]),
            DomainModuleStatus("Webhooks/Integrations", "implemented", "implemented", "implemented", "implemented", "planned", ["Users"]),
        ]

    def execution_graph(self) -> list[DependencyStep]:
        return [
            DependencyStep(1, "users", []),
            DependencyStep(2, "schemas/custom fields/categories/stages", ["users"]),
            DependencyStep(3, "contacts/companies", ["users", "schemas/custom fields/categories/stages"]),
            DependencyStep(4, "deals", ["contacts/companies", "schemas/custom fields/categories/stages"]),
            DependencyStep(5, "crm comments", ["deals"]),
            DependencyStep(6, "crm file refs", ["crm comments"]),
            DependencyStep(7, "groups/projects", ["users"]),
            DependencyStep(8, "tasks", ["users", "groups/projects"]),
            DependencyStep(9, "comments", ["tasks"]),
            DependencyStep(10, "file refs", ["comments"]),
            DependencyStep(11, "verification", ["crm file refs", "file refs"]),
            DependencyStep(12, "delta/cutover", ["verification"]),
        ]
