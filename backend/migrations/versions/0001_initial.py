"""Initial evidence, master-data, intelligence and governance schema."""

from alembic import op

from app.database import Base
from app import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The metadata is the reviewed baseline. Future migrations use explicit
    # Alembic operations generated from diffs against this revision.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    # Freeze the employee-number rule as it existed at revision 0001. The
    # following revision deliberately evolves it to active mappings only.
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


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
