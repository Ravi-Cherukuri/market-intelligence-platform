"""Preview and commit endpoints for administrator-uploaded master data."""

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_company
from app.database import get_db
from app.models import ProductOwnership
from app.services.imports import (
    commit_employees,
    commit_prices,
    commit_products,
    preview_employees,
    preview_prices,
    preview_products,
    read_tabular_upload,
)

router = APIRouter(
    prefix="/admin/companies/{company_id}/masters",
    tags=["masters"],
    dependencies=[Depends(require_admin), Depends(require_company)],
)


async def _rows(upload: UploadFile) -> list[dict[str, str]]:
    if not upload.filename or not upload.filename.casefold().endswith((".csv", ".xlsx")):
        raise HTTPException(status_code=422, detail="Upload a CSV or XLSX file")
    content = await upload.read()
    if len(content) > 10_000_000:
        raise HTTPException(status_code=413, detail="Master file exceeds 10 MB")
    try:
        return read_tabular_upload(upload.filename, content)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="The uploaded file could not be parsed") from exc


@router.post("/employees/{mode}")
async def upload_employees(
    company_id: str,
    mode: Literal["preview", "commit"],
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
) -> dict:
    preview = preview_employees(await _rows(file))
    if mode == "preview" or preview.errors:
        return preview.as_dict()
    try:
        changed = commit_employees(session, company_id, preview)
        session.commit()
    except (ValueError, IntegrityError) as exc:
        session.rollback()
        detail = str(exc) if isinstance(exc, ValueError) else "Employee code or active WhatsApp number already exists"
        raise HTTPException(status_code=409, detail=detail) from exc
    return {"valid": True, "committed": changed, "errors": []}


@router.post("/products/{ownership}/{mode}")
async def upload_products(
    company_id: str,
    ownership: ProductOwnership,
    mode: Literal["preview", "commit"],
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
) -> dict:
    preview = preview_products(await _rows(file), ownership)
    if mode == "preview" or preview.errors:
        return preview.as_dict()
    changed = commit_products(session, company_id, preview)
    session.commit()
    return {"valid": True, "committed": changed, "errors": []}


@router.post("/competition-prices/{mode}")
async def upload_competition_prices(
    company_id: str,
    mode: Literal["preview", "commit"],
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
) -> dict:
    preview = preview_prices(session, company_id, await _rows(file))
    if mode == "preview" or preview.errors:
        return preview.as_dict()
    changed = commit_prices(session, company_id, preview)
    session.commit()
    return {"valid": True, "committed": changed, "errors": []}
