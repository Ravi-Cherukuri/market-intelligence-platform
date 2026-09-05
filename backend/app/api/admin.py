from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.ai.openai_client import OpenAIIntelligenceClient
from app.config import Settings, get_settings
from app.database import get_db
from app.models import Company, Employee, FieldConversation, FieldMessage, Signal, WhatsAppChannel
from app.services.weekly_intelligence import get_weekly_intelligence

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


@router.get("/weekly-intelligence")
def weekly_intelligence(
    week_ending: date | None = Query(default=None),
    state: str | None = Query(default=None, min_length=2, max_length=100),
    business_scope: str = Query(default="all", pattern="^(all|own_business|competitor)$"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    company = session.scalar(select(Company).where(Company.active.is_(True)).order_by(Company.created_at))
    if not company:
        raise HTTPException(status_code=503, detail="Pilot company has not been initialized")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Weekly intelligence synthesis is not configured")
    selected_date = week_ending or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if selected_date > datetime.now(ZoneInfo("Asia/Kolkata")).date():
        raise HTTPException(status_code=422, detail="Week-ending date cannot be in the future")
    if state:
        known = session.scalar(
            select(Employee.id).where(
                Employee.company_id == company.id,
                Employee.active.is_(True),
                Employee.state == state,
            )
        )
        if not known:
            raise HTTPException(status_code=422, detail="State is not present in the active employee master")
    try:
        result = get_weekly_intelligence(
            session,
            company,
            OpenAIIntelligenceClient(settings.openai_api_key),
            week_ending=selected_date,
            state=state,
            business_scope=business_scope,
        )
        session.commit()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail="Weekly intelligence synthesis could not be generated") from exc
