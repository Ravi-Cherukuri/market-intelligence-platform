from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.database import get_db
from app.models import Company, Employee, FieldConversation, FieldMessage, Signal, WhatsAppChannel

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/setup")
def setup(session: Session = Depends(get_db)) -> dict[str, str | bool]:
    company = session.scalar(select(Company).where(Company.active.is_(True)).order_by(Company.created_at))
    if not company:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Pilot company has not been initialized")
    channel = session.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.company_id == company.id,
            WhatsAppChannel.active.is_(True),
        )
    )
    return {
        "company_id": company.id,
        "company_name": company.name,
        "whatsapp_configured": channel is not None,
    }


@router.get("/overview")
def overview(session: Session = Depends(get_db)) -> dict[str, int]:
    return {
        "active_employees": session.scalar(select(func.count()).select_from(Employee).where(Employee.active.is_(True))) or 0,
        "conversations": session.scalar(select(func.count()).select_from(FieldConversation)) or 0,
        "messages": session.scalar(select(func.count()).select_from(FieldMessage)) or 0,
        "signals": session.scalar(select(func.count()).select_from(Signal)) or 0,
    }
