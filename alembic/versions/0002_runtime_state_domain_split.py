"""split runtime state into jobs/checkpoints/logs

Revision ID: 0002_runtime_state_domain_split
Revises: 0001_init_runtime_state
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_runtime_state_domain_split"
down_revision = "0001_init_runtime_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "migration_jobs",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        sa.Column("source_portal", sa.String(length=255), nullable=False),
        sa.Column("target_portal", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("migration_plans", sa.Column("job_id", sa.String(length=64), nullable=True))
    op.create_index("ix_migration_plans_job_id", "migration_plans", ["job_id"])

    dialect = op.get_bind().dialect.name
    if dialect.startswith("mysql"):
        op.execute(
            sa.text(
                """
                INSERT INTO migration_jobs (job_id, source_portal, target_portal, created_at)
                SELECT CONCAT('legacy-', plan_id), source_portal, target_portal, created_at
                FROM migration_plans
                """
            )
        )
        op.execute(sa.text("UPDATE migration_plans SET job_id = CONCAT('legacy-', plan_id) WHERE job_id IS NULL"))
    else:
        op.execute(
            sa.text(
                """
                INSERT INTO migration_jobs (job_id, source_portal, target_portal, created_at)
                SELECT 'legacy-' || plan_id, source_portal, target_portal, created_at
                FROM migration_plans
                """
            )
        )
        op.execute(sa.text("UPDATE migration_plans SET job_id = 'legacy-' || plan_id WHERE job_id IS NULL"))

    with op.batch_alter_table("migration_plans") as batch_op:
        batch_op.alter_column("job_id", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_foreign_key("fk_migration_plans_job_id", "migration_jobs", ["job_id"], ["job_id"])

    with op.batch_alter_table("migration_runs") as batch_op:
        batch_op.create_foreign_key("fk_migration_runs_plan_id", "migration_plans", ["plan_id"], ["plan_id"])

    op.create_table(
        "migration_checkpoints",
        sa.Column("checkpoint_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_token", sa.String(length=128), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["migration_runs.run_id"], name="fk_migration_checkpoints_run_id"),
    )
    op.create_index("ix_migration_checkpoints_run_id", "migration_checkpoints", ["run_id"])

    op.create_table(
        "migration_logs",
        sa.Column("log_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["migration_runs.run_id"], name="fk_migration_logs_run_id"),
    )
    op.create_index("ix_migration_logs_run_id", "migration_logs", ["run_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO migration_checkpoints (run_id, checkpoint_token, state_json, created_at)
            SELECT run_id, checkpoint_token, NULL, updated_at
            FROM migration_runs
            WHERE checkpoint_token IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_migration_logs_run_id", table_name="migration_logs")
    op.drop_table("migration_logs")

    op.drop_index("ix_migration_checkpoints_run_id", table_name="migration_checkpoints")
    op.drop_table("migration_checkpoints")

    with op.batch_alter_table("migration_runs") as batch_op:
        batch_op.drop_constraint("fk_migration_runs_plan_id", type_="foreignkey")

    with op.batch_alter_table("migration_plans") as batch_op:
        batch_op.drop_constraint("fk_migration_plans_job_id", type_="foreignkey")

    op.drop_index("ix_migration_plans_job_id", table_name="migration_plans")
    with op.batch_alter_table("migration_plans") as batch_op:
        batch_op.drop_column("job_id")

    op.drop_table("migration_jobs")
