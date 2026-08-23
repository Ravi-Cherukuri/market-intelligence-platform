"""Migration checks for schema changes that fresh metadata tests cannot cover."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Company, Employee, EmploymentType

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _upgrade(database_url: str, revision: str) -> None:
    environment = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "test"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        check=True,
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_employee_whatsapp_constraint_migrates_to_active_only(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    _upgrade(database_url, "0001_initial")
    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "uq_employee_whatsapp_company" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("employees")
    }
    assert "uq_employee_active_whatsapp_company" not in {
        index["name"] for index in inspector.get_indexes("employees")
    }

    _upgrade(database_url, "head")
    inspector = inspect(engine)
    assert "uq_employee_whatsapp_company" not in {
        constraint["name"] for constraint in inspector.get_unique_constraints("employees")
    }
    assert "uq_employee_active_whatsapp_company" in {
        index["name"] for index in inspector.get_indexes("employees")
    }

    with Session(engine) as session:
        company = Company(name="Migration Pilot")
        session.add(company)
        session.flush()
        session.add_all(
            [
                Employee(
                    company_id=company.id,
                    employee_code="FORMER",
                    employment_type=EmploymentType.FULL_TIME,
                    state="Maharashtra",
                    whatsapp_number="919876543210",
                    active=False,
                ),
                Employee(
                    company_id=company.id,
                    employee_code="CURRENT",
                    employment_type=EmploymentType.FULL_TIME,
                    state="Maharashtra",
                    whatsapp_number="919876543210",
                    active=True,
                ),
            ]
        )
        session.commit()

    engine.dispose()
