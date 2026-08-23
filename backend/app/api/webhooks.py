"""Meta WhatsApp Cloud API webhook endpoints."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.security import verify_meta_signature
from app.services.ingestion import ingest_whatsapp_payload

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


@router.get("")
def verify_webhook(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
    settings: Settings = Depends(get_settings),
) -> Response:
    if mode != "subscribe" or not settings.whatsapp_verify_token or verify_token != settings.whatsapp_verify_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")
    return Response(content=challenge or "", media_type="text/plain")


@router.post("")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int | str]:
    raw_body = await request.body()
    if len(raw_body) > settings.max_webhook_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook payload too large")
    if settings.whatsapp_signature_required and not verify_meta_signature(
        raw_body, x_hub_signature_256, settings.whatsapp_app_secret
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc

    try:
        results = ingest_whatsapp_payload(session, payload, settings.conversation_timeout_minutes)
        session.commit()
    except IntegrityError:
        # A concurrent Meta retry may win the unique receipt insert after our
        # initial lookup. Roll back and replay once; committed receipts then
        # turn the replay into deterministic duplicates.
        session.rollback()
        results = ingest_whatsapp_payload(session, payload, settings.conversation_timeout_minutes)
        session.commit()
    accepted = sum(result.status == "accepted" for result in results)
    return {"status": "accepted", "messages_seen": len(results), "messages_persisted": accepted}
