from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_company
from app.database import get_db
from app.models import AuditEvent, RetentionPolicy

router = APIRouter(
    prefix="/admin/companies/{company_id}/retention",
    tags=["retention"],
    dependencies=[Depends(require_admin), Depends(require_company)],
)

DEFAULT_RETENTION = {
    "raw_messages": 730,
    "media": 730,
    "transcripts": 1825,
    "structured_observations": 1825,
    "reports": None,
    "audit_records": 1825,
}


class RetentionUpdate(BaseModel):
    retention_days: int | None = Field(default=None, ge=1, le=36500)
    enabled: bool = True


@router.get("")
def list_retention(company_id: str, session: Session = Depends(get_db)) -> list[dict]:
    policies = {
        item.data_type: item
        for item in session.scalars(select(RetentionPolicy).where(RetentionPolicy.company_id == company_id))
    }
    return [
        {
            "data_type": data_type,
            "retention_days": policies[data_type].retention_days if data_type in policies else days,
            "enabled": policies[data_type].enabled if data_type in policies else True,
        }
        for data_type, days in DEFAULT_RETENTION.items()
    ]


@router.put("/{data_type}")
def update_retention(
    company_id: str,
    data_type: str,
    update: RetentionUpdate,
    session: Session = Depends(get_db),
) -> dict:
    if data_type not in DEFAULT_RETENTION:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Unknown retention data type")
    policy = session.scalar(
        select(RetentionPolicy).where(
            RetentionPolicy.company_id == company_id,
            RetentionPolicy.data_type == data_type,
        )
    )
    previous = policy.retention_days if policy else DEFAULT_RETENTION[data_type]
    if policy is None:
        policy = RetentionPolicy(company_id=company_id, data_type=data_type)
        session.add(policy)
    policy.retention_days = update.retention_days
    policy.enabled = update.enabled
    session.add(
        AuditEvent(
            company_id=company_id,
            event_type="retention.policy_changed",
            actor_type="admin",
            actor_reference="Admin",
            metadata_json={"data_type": data_type, "previous_days": previous, "new_days": update.retention_days},
        )
    )
    session.commit()
    return {"data_type": data_type, "retention_days": update.retention_days, "enabled": update.enabled}
