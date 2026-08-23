"""Request dependencies, including temporary placeholder administration auth."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Company
from app.security import constant_time_credentials_match

basic_auth = HTTPBasic(auto_error=False)


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    settings: Settings = Depends(get_settings),
) -> str:
    if not credentials or not constant_time_credentials_match(
        credentials.username,
        credentials.password,
        settings.admin_username,
        settings.admin_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid pilot administrator credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def require_company(company_id: str, session: Session = Depends(get_db)) -> Company:
    company = session.get(Company, company_id)
    if not company or not company.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company
