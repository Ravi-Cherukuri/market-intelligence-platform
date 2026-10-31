"""Request dependencies, including temporary placeholder administration auth."""

import hmac

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Company
from app.security import constant_time_credentials_match, verify_password

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


def require_report_or_admin(
    credentials: HTTPBasicCredentials | None = Depends(basic_auth),
    settings: Settings = Depends(get_settings),
    x_fieldintel_role: str | None = Header(default=None),
    x_fieldintel_auth: str | None = Header(default=None),
) -> str:
    if credentials and constant_time_credentials_match(
        credentials.username, credentials.password, settings.admin_username, settings.admin_password
    ):
        return "admin"
    if (
        credentials
        and hmac.compare_digest(credentials.username, settings.report_username)
        and verify_password(credentials.password, settings.report_password_hash)
    ):
        return "reports"
    expected_internal = hmac.new(
        settings.report_password_hash.encode(), b"field-intelligence:internal:reports", "sha256"
    ).hexdigest()
    if (
        x_fieldintel_role == "reports"
        and x_fieldintel_auth
        and hmac.compare_digest(x_fieldintel_auth, expected_internal)
    ):
        return "reports"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid report credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


def require_company(company_id: str, session: Session = Depends(get_db)) -> Company:
    company = session.get(Company, company_id)
    if not company or not company.active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company
