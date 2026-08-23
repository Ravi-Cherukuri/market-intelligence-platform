from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from fastapi import Depends

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(session: Session = Depends(get_db)) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready"}
