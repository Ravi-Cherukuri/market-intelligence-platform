"""Add business scope classification and cached weekly briefs."""

from alembic import op
import sqlalchemy as sa

revision = "0003_weekly_intelligence"
down_revision = "0002_active_employee_whatsapp"
branch_labels = None
depends_on = None
AUTOMATED_ROLLBACK_SAFE = True


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column(
            "business_scope",
            sa.Enum("OWN_BUSINESS", "COMPETITOR", name="businessscope", native_enum=False),
            nullable=False,
            server_default="COMPETITOR",
        ),
    )
    op.create_table(
        "weekly_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("state_scope", sa.String(length=100), nullable=False),
        sa.Column("business_scope", sa.String(length=30), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "state_scope", "business_scope", "period_end", "source_fingerprint",
            name="uq_weekly_brief_fingerprint",
        ),
    )
    op.create_index(op.f("ix_weekly_briefs_company_id"), "weekly_briefs", ["company_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_weekly_briefs_company_id"), table_name="weekly_briefs")
    op.drop_table("weekly_briefs")
    op.drop_column("observations", "business_scope")
