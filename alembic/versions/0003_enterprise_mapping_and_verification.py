"""enterprise mapping, user review queue and verification tables

Revision ID: 0003_enterprise_mapping_and_verification
Revises: 0002_runtime_state_domain_split
Create Date: 2026-03-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_enterprise_mapping_and_verification"
down_revision = "0002_runtime_state_domain_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "migration_mappings",
        sa.Column("mapping_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_uid", sa.String(length=255), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("target_uid", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolution_strategy", sa.String(length=64), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("linked_parent_type", sa.String(length=64), nullable=True),
        sa.Column("linked_parent_source_id", sa.String(length=128), nullable=True),
        sa.Column("linked_parent_target_id", sa.String(length=128), nullable=True),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("error_payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_type", "source_id", name="uq_migration_mappings_entity_source"),
    )
    op.create_index("ix_migration_mappings_entity_type", "migration_mappings", ["entity_type"])
    op.create_index("ix_migration_mappings_source_uid", "migration_mappings", ["source_uid"])
    op.create_index("ix_migration_mappings_target_id", "migration_mappings", ["target_id"])
    op.create_index("ix_migration_mappings_status", "migration_mappings", ["status"])
    op.create_index("ix_migration_mappings_verification_status", "migration_mappings", ["verification_status"])
    op.create_index("ix_migration_mappings_created_at", "migration_mappings", ["created_at"])
    op.create_index("ix_migration_mappings_updated_at", "migration_mappings", ["updated_at"])

    op.create_table(
        "migration_user_review_queue",
        sa.Column("review_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_uid", sa.String(length=255), nullable=True),
        sa.Column("candidates_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_migration_user_review_queue_source_id", "migration_user_review_queue", ["source_id"])
    op.create_index("ix_migration_user_review_queue_status", "migration_user_review_queue", ["status"])
    op.create_index("ix_migration_user_review_queue_created_at", "migration_user_review_queue", ["created_at"])
    op.create_index("ix_migration_user_review_queue_updated_at", "migration_user_review_queue", ["updated_at"])

    op.create_table(
        "migration_verification_results",
        sa.Column("result_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("check_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["migration_runs.run_id"], name="fk_migration_verification_results_run_id"),
    )
    op.create_index("ix_migration_verification_results_run_id", "migration_verification_results", ["run_id"])
    op.create_index("ix_migration_verification_results_check_type", "migration_verification_results", ["check_type"])
    op.create_index("ix_migration_verification_results_entity_type", "migration_verification_results", ["entity_type"])
    op.create_index("ix_migration_verification_results_status", "migration_verification_results", ["status"])
    op.create_index("ix_migration_verification_results_created_at", "migration_verification_results", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_migration_verification_results_created_at", table_name="migration_verification_results")
    op.drop_index("ix_migration_verification_results_status", table_name="migration_verification_results")
    op.drop_index("ix_migration_verification_results_entity_type", table_name="migration_verification_results")
    op.drop_index("ix_migration_verification_results_check_type", table_name="migration_verification_results")
    op.drop_index("ix_migration_verification_results_run_id", table_name="migration_verification_results")
    op.drop_table("migration_verification_results")

    op.drop_index("ix_migration_user_review_queue_updated_at", table_name="migration_user_review_queue")
    op.drop_index("ix_migration_user_review_queue_created_at", table_name="migration_user_review_queue")
    op.drop_index("ix_migration_user_review_queue_status", table_name="migration_user_review_queue")
    op.drop_index("ix_migration_user_review_queue_source_id", table_name="migration_user_review_queue")
    op.drop_table("migration_user_review_queue")

    op.drop_index("ix_migration_mappings_updated_at", table_name="migration_mappings")
    op.drop_index("ix_migration_mappings_created_at", table_name="migration_mappings")
    op.drop_index("ix_migration_mappings_verification_status", table_name="migration_mappings")
    op.drop_index("ix_migration_mappings_status", table_name="migration_mappings")
    op.drop_index("ix_migration_mappings_target_id", table_name="migration_mappings")
    op.drop_index("ix_migration_mappings_source_uid", table_name="migration_mappings")
    op.drop_index("ix_migration_mappings_entity_type", table_name="migration_mappings")
    op.drop_table("migration_mappings")
