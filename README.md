# b24-migration-runtime (enterprise baseline extension)

Production-oriented runtime for deterministic Bitrix24 migration with **CLI + Web UI** over one shared service layer.

## Summary

This repository keeps the already implemented baseline (RuntimeService, CLI wiring, FastAPI/Jinja2/HTMX UI, audit persistence, Docker) and adds first full **data-plane sprint**:

- users/groups/projects/tasks/comments/file references end-to-end migration services;
- canonical source↔target mapping subsystem (without relying on ID equality);
- user conflict policy with manual review queue + manual override API/CLI;
- dependency-aware execution safety (users unresolved => dependent domains blocked);
- expanded verification (`verify:counts`, `verify:relations`, `verify:integrity`, `verify:files`) persisted in DB;
- cleanup/delta/cutover planning with safety rails (dry-run first, preserve users policy);
- enterprise UI screen for matrix/mappings/conflicts/verification/cleanup/delta.

## What is treated as existing baseline

Unchanged architectural baseline from previous PR:

- RuntimeService / shared service layer.
- CLI commands and deterministic JSON output style.
- FastAPI + Jinja2/HTMX MVP dashboard/config/run pages.
- Persistent runtime/audit storage.
- Dockerfile, docker-compose, `.env.example`, config templates.

## Supported migration matrix

| Entity | Status | Source API | Target API | Dependencies | Mapping | Verification | Delta | Cleanup | Risk notes |
|---|---|---|---|---|---|---|---|---|---|
| users | implemented | user.get/list | user.get/list | - | XML_ID/email/login/manual | counts+relations+integrity | incremental match refresh | preserve target users only | ambiguous identity review queue |
| groups | implemented | sonet_group.get | sonet_group.create/update | users | canonical map | counts+relations+integrity | planned | preview only | blocked on unresolved user_map |
| projects | implemented | sonet_group.get(project) | sonet_group.create(project) | users, groups | canonical map | counts+relations+integrity | planned | preview only | owner/member links via user_map |
| tasks | implemented | tasks.task.list/get | tasks.task.add/update | users, groups/projects | canonical map | counts+relations+integrity | planned | preview only | blocks on unresolved user/group/project refs |
| crm | partial | crm.*.list | crm.*.add/update | users, schemas | canonical map | counts+relations+integrity | planned | preview only | stage/category remap |
| business processes | partial | bizproc.workflow.template.list | bizproc.workflow.template.add | users, schemas | canonical map | relations+integrity | planned | preview only | template constants/users |
| smart processes | partial | crm.type + crm.item | crm.type + crm.item | users, schemas | canonical map | counts+relations+integrity | planned | preview only | type before items |
| comments | implemented | task/crm comment APIs | timeline/comment APIs | tasks, crm, smart processes | canonical map | counts+relations+integrity | planned | preview only | comment->task and comment->author verification |
| files | partial | disk.file.* | disk.file.upload | comments, crm, tasks | canonical map | files+integrity | planned | preview only | metadata/reference layer implemented, payload copy planned |
| reports | planned | report.* | report.* | users, crm/tasks/items | canonical map | relations | planned | preview only | API variance by plan |
| robots | partial | crm.automation.* | crm.automation.* | bp, schemas | canonical map | relations+integrity | planned | preview only | stage/action remap |
| webhooks | implemented | event.bind/list | event.bind/list | users | canonical map | integrity | planned | preview only | rotate secrets at cutover |
| automation | partial | bizproc + crm.automation.* | bizproc + crm.automation.* | bp, robots | canonical map | relations+integrity | planned | preview only | tenant-specific references |

## Unified mapping layer

Persisted table `migration_mappings` fields:

- `entity_type`, `source_id`, `source_uid`, `target_id`, `target_uid`
- `status`, `resolution_strategy`, `verification_status`
- `linked_parent_type`, `linked_parent_source_id`, `linked_parent_target_id`
- `payload_hash`, `created_at`, `updated_at`, `error_payload_json`

Supported entities in canonical mapping subsystem:

- users, groups, projects, tasks, crm entities, comments, files,
- bp templates, robots, smart process types/items, reports, webhooks.

## User conflict policy

`UserResolutionService` applies matching order:

1. XML_ID
2. email
3. login
4. otherwise manual review queue

Rules:

- target users are **preserved** (not deleted by cleanup);
- ambiguous matches go to `migration_user_review_queue`;
- unmatched users are stored as mapping rows with `status=unmatched` and explicit error payload;
- all non-user references are expected to resolve through `user_map` mapping rows.

## Domain modules and execution graph

Domain lifecycle tracking is provided for:

- Users
- Groups/Projects
- Tasks
- CRM
- Smart Processes
- Business Processes / Robots / Automation
- Comments
- Files
- Reports
- Webhooks / Integrations

Execution order graph:

1. users
2. groups/projects
3. tasks
4. comments
5. file refs
6. schemas/custom fields/categories/stages
7. BP/robots/automation schemas
8. CRM/smart-process items
9. reports
10. verification
11. delta
12. cutover

## Verification coverage

Checks persisted in `migration_verification_results`:

- `verify:counts`
- `verify:relations`
- `verify:integrity`
- `verify:files`

Relation rules covered (including new sprint domains):

- task -> creator/responsible/accomplices/auditors user mappings
- task -> group/project
- comment -> task
- comment -> author
- file ref -> task
- deal -> company/contact
- crm entity -> stage/category/custom field
- bp template -> user/field/entity-type
- robot -> stage/action/assignee
- smart process item -> type/field/entity
- report -> owner/filter/source entity
- webhook/integration -> target binding validity

Verification output is available in DB, CLI and Web UI.

## Delta / cutover / cleanup flow

Implemented control-plane commands/services:

- target inspection
- cleanup-plan (dry-run safety by default)
- cleanup-execute (unsafe destructive path blocked without explicit safe plan)
- preserve users policy
- delta plan/execute
- cutover readiness based on unresolved mappings + verification result

Rules:

- no destructive cleanup without explicit dry-run report;
- no silent overwrite of target defaults.

## Web UI additions

New enterprise view (`/enterprise`) extends MVP dashboard with:

- migration matrix
- domain module statuses
- dependency graph
- users mapping review queue
- verification results
- cleanup preview
- delta readiness
- entity mapping audit overview

## CLI additions

Core commands kept from baseline:

- `b24-runtime create-job`
- `b24-runtime plan`
- `b24-runtime execute`
- `b24-runtime status`
- `b24-runtime checkpoint`
- `b24-runtime report`
- `b24-runtime verify`
- `b24-runtime deployment:check`

Enterprise extensions:

- `matrix`
- `domains`
- `mappings`
- `users:discover`
- `users:map`
- `users:review`
- `groups:sync`
- `projects:sync`
- `tasks:migrate`
- `verify:counts`
- `verify:relations`
- `verify:integrity`
- `verify:files`
- `verify:results`
- `cleanup:plan`
- `cleanup:execute`
- `delta:plan`
- `delta:execute`
- `cutover:readiness`

## Docker/run

Existing Docker setup remains valid (`docker compose up --build`). Enterprise additions are schema-compatible via new Alembic revision `0003_enterprise_mapping_and_verification`.

Config keeps `runtime_mode` and **MySQL-only** production rule from baseline (`runtime_mode: production` + MySQL URL in production).

## Testing

New/updated tests include:

- user matching policy (XML_ID/email/login/manual), ambiguous queue, manual override
- unresolved users blocking groups/tasks migration
- task/comment/file reference relation checks
- file refs verification with explicit partial payload-copy status
- CLI regression for new data-plane commands
- API tests for mapping review + domain migration endpoints
- existing CLI/web regression

Run with:

```bash
pytest
```
