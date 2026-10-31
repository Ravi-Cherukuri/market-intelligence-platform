"""Read-only intelligence APIs available to administrators and report viewers."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.openai_client import OpenAIIntelligenceClient
from app.api.dependencies import require_report_or_admin
from app.config import Settings, get_settings
from app.database import get_db
from app.geography import INDIAN_STATES_AND_UNION_TERRITORIES
from app.models import Company
from app.services.weekly_intelligence import get_weekly_intelligence

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/session")
def report_session(role: str = Depends(require_report_or_admin)) -> dict[str, object]:
    return {"role": role, "can_admin": role == "admin", "default_state": "Tamilnadu"}


def generate_weekly_intelligence(
    week_ending: date | None,
    state: str | None,
    business_scope: str,
    session: Session,
    settings: Settings,
) -> dict[str, object]:
    company = session.scalar(select(Company).where(Company.active.is_(True)).order_by(Company.created_at))
    if not company:
        raise HTTPException(status_code=503, detail="Pilot company has not been initialized")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="Weekly intelligence synthesis is not configured")
    selected_date = week_ending or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if selected_date > datetime.now(ZoneInfo("Asia/Kolkata")).date():
        raise HTTPException(status_code=422, detail="Week-ending date cannot be in the future")
    if state and state not in INDIAN_STATES_AND_UNION_TERRITORIES:
        raise HTTPException(status_code=422, detail="Select a valid Indian state or union territory")
    try:
        result = get_weekly_intelligence(
            session, company, OpenAIIntelligenceClient(settings.openai_api_key),
            week_ending=selected_date, state=state, business_scope=business_scope,
        )
        session.commit()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail="Weekly intelligence synthesis could not be generated") from exc


@router.get("/weekly-intelligence", dependencies=[Depends(require_report_or_admin)])
def weekly_intelligence(
    week_ending: date | None = Query(default=None),
    state: str | None = Query(default=None, min_length=2, max_length=100),
    business_scope: str = Query(default="all", pattern="^(all|own_business|competitor)$"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    return generate_weekly_intelligence(week_ending, state, business_scope, session, settings)
