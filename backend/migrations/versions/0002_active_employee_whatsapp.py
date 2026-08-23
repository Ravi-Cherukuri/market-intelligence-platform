"""Allow a WhatsApp number to move from an inactive to an active employee."""

from alembic import op
import sqlalchemy as sa

revision = "0002_active_employee_whatsapp"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("employees", recreate="always") as batch:
            batch.drop_constraint("uq_employee_whatsapp_company", type_="unique")
    else:
        op.drop_constraint("uq_employee_whatsapp_company", "employees", type_="unique")

    op.create_index(
        "uq_employee_active_whatsapp_company",
        "employees",
        ["company_id", "whatsapp_number"],
        unique=True,
        postgresql_where=sa.text("active"),
        sqlite_where=sa.text("active = 1"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("uq_employee_active_whatsapp_company", table_name="employees")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("employees", recreate="always") as batch:
            batch.create_unique_constraint(
                "uq_employee_whatsapp_company", ["company_id", "whatsapp_number"]
            )
    else:
        op.create_unique_constraint(
            "uq_employee_whatsapp_company", "employees", ["company_id", "whatsapp_number"]
        )
