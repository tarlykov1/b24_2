"""init runtime state tables

Revision ID: 0001_init_runtime_state
Revises: 
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init_runtime_state"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "migration_plans",
        sa.Column("plan_id", sa.String(length=64), primary_key=True),
        sa.Column("source_portal", sa.String(length=255), nullable=False),
        sa.Column("target_portal", sa.String(length=255), nullable=False),
        sa.Column("scope_csv", sa.Text(), nullable=False),
        sa.Column("deterministic_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_migration_plans_deterministic_hash", "migration_plans", ["deterministic_hash"])

    op.create_table(
        "migration_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("processed_items", sa.Integer(), nullable=False),
        sa.Column("checkpoint_token", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_migration_runs_plan_id", "migration_runs", ["plan_id"])
    op.create_index("ix_migration_runs_status", "migration_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_migration_runs_status", table_name="migration_runs")
    op.drop_index("ix_migration_runs_plan_id", table_name="migration_runs")
    op.drop_table("migration_runs")
    op.drop_index("ix_migration_plans_deterministic_hash", table_name="migration_plans")
    op.drop_table("migration_plans")
