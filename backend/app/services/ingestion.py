"""Transactional WhatsApp message ingestion.

The webhook only authenticates, normalizes and durably stores work. Media
download, transcription and AI processing are intentionally left to workers so
Meta retries cannot be triggered by slow external providers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.conversations import belongs_to_open_conversation, normalized_command, utc_aware
from app.domain.identity import InvalidPhoneNumber, normalize_indian_whatsapp_number
from app.models import (
    AuditEvent,
    ConversationStatus,
    Employee,
    FieldConversation,
    FieldMessage,
    InboundMessageReceipt,
    MediaAsset,
    MessageType,
    OutboundMessage,
    WhatsAppChannel,
)


@dataclass(frozen=True)
class IngestionResult:
    status: str
    message_id: str | None = None
    conversation_id: str | None = None


def _provider_datetime(timestamp: str | int | None) -> datetime:
    if timestamp is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)


def _message_parts(message: dict[str, Any]) -> tuple[MessageType, str | None, str | None]:
    provider_type = str(message.get("type", "unsupported"))
    if provider_type == "text":
        return MessageType.TEXT, message.get("text", {}).get("body"), None
    # Documents are deliberately outside the low-memory pilot scope. Voice
    # notes and photos arrive through Meta, are size/type checked downstream,
    # and are never decoded or executed by this service.
    if provider_type in {"audio", "image"}:
        payload = message.get(provider_type, {})
        text = payload.get("caption")
        return MessageType(provider_type), text, payload.get("id")
    if provider_type == "location":
        location = message.get("location", {})
        text = f"{location.get('latitude')},{location.get('longitude')}"
        return MessageType.LOCATION, text, None
    return MessageType.UNSUPPORTED, None, None


def _employee_snapshot(employee: Employee) -> dict[str, Any]:
    return {
        "employee_code": employee.employee_code,
        "employment_type": employee.employment_type.value,
        "designation": employee.designation,
        "territory_code": employee.territory_code,
        "state": employee.state,
    }


def _unknown_sender_reference(wa_id: str) -> str:
    # Retain a stable pseudonymous reference for abuse investigation without
    # keeping the unregistered person's raw phone number.
    return hashlib.sha256(wa_id.encode("utf-8")).hexdigest()[:20]


def ingest_whatsapp_message(
    session: Session,
    *,
    phone_number_id: str,
    message: dict[str, Any],
    timeout_minutes: int,
) -> IngestionResult:
    provider_message_id = str(message.get("id", ""))
    if not provider_message_id:
        return IngestionResult("malformed")

    if session.scalar(
        select(InboundMessageReceipt.id).where(InboundMessageReceipt.provider_message_id == provider_message_id)
    ):
        return IngestionResult("duplicate")

    channel = session.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.phone_number_id == phone_number_id,
            WhatsAppChannel.active.is_(True),
        )
    )
    if not channel:
        session.add(
            InboundMessageReceipt(
                company_id=None,
                provider_message_id=provider_message_id,
                disposition="unknown_destination",
                received_at=_provider_datetime(message.get("timestamp")),
            )
        )
        session.flush()
        session.add(
            AuditEvent(
                company_id=None,
                event_type="whatsapp.unknown_destination",
                actor_type="system",
                metadata_json={"phone_number_id": phone_number_id, "provider_message_id": provider_message_id},
            )
        )
        return IngestionResult("unknown_destination")

    try:
        wa_id = normalize_indian_whatsapp_number(str(message.get("from", "")))
    except InvalidPhoneNumber:
        return IngestionResult("malformed_sender")

    employee = session.scalar(
        select(Employee).where(
            Employee.company_id == channel.company_id,
            Employee.whatsapp_number == wa_id,
            Employee.active.is_(True),
        )
    )
    if not employee:
        session.add(
            InboundMessageReceipt(
                company_id=channel.company_id,
                provider_message_id=provider_message_id,
                disposition="unregistered_sender",
                received_at=_provider_datetime(message.get("timestamp")),
            )
        )
        session.flush()
        session.add(
            AuditEvent(
                company_id=channel.company_id,
                event_type="whatsapp.unregistered_sender",
                actor_type="external_sender",
                actor_reference=_unknown_sender_reference(wa_id),
                metadata_json={"provider_message_id": provider_message_id},
            )
        )
        session.add(
            OutboundMessage(
                company_id=channel.company_id,
                channel_id=channel.id,
                recipient_wa_id=wa_id,
                message_kind="unregistered_sender",
                body="Your number is not registered. Please contact your administrator.",
            )
        )
        return IngestionResult("unregistered_sender")

    received_at = _provider_datetime(message.get("timestamp"))
    message_type, text_content, provider_media_id = _message_parts(message)
    command = normalized_command(text_content) if message_type == MessageType.TEXT else None

    # Unsupported attachments are acknowledged without becoming field
    # evidence. In particular, they must not open/extend a conversation or be
    # passed to the intelligence layer as an empty "media awaiting" message.
    if message_type == MessageType.UNSUPPORTED:
        session.add(
            InboundMessageReceipt(
                company_id=channel.company_id,
                provider_message_id=provider_message_id,
                disposition="unsupported_attachment",
                received_at=received_at,
            )
        )
        session.flush()
        session.add(
            AuditEvent(
                company_id=channel.company_id,
                event_type="whatsapp.unsupported_attachment",
                actor_type="employee",
                actor_reference=employee.employee_code,
                metadata_json={"provider_message_id": provider_message_id},
            )
        )
        session.add(
            OutboundMessage(
                company_id=channel.company_id,
                channel_id=channel.id,
                recipient_wa_id=wa_id,
                message_kind="unsupported_attachment",
                body="This attachment type is not supported. Please send text, a voice note, or a photo.",
            )
        )
        return IngestionResult("unsupported")

    # Meta media envelopes must contain an id that can be fetched through the
    # authenticated Graph API. A malformed envelope is acknowledged and
    # audited, but must not create evidence that waits forever for media.
    if message_type in {MessageType.AUDIO, MessageType.IMAGE} and not provider_media_id:
        session.add(
            InboundMessageReceipt(
                company_id=channel.company_id,
                provider_message_id=provider_message_id,
                disposition="malformed_media",
                received_at=received_at,
            )
        )
        session.flush()
        session.add(
            AuditEvent(
                company_id=channel.company_id,
                event_type="whatsapp.malformed_media",
                actor_type="employee",
                actor_reference=employee.employee_code,
                metadata_json={"provider_message_id": provider_message_id, "message_type": message_type.value},
            )
        )
        return IngestionResult("malformed_media")

    conversation = session.scalar(
        select(FieldConversation)
        .where(
            FieldConversation.company_id == channel.company_id,
            FieldConversation.employee_id == employee.id,
            FieldConversation.status == ConversationStatus.OPEN,
        )
        .order_by(FieldConversation.last_message_at.desc())
    )

    if conversation and not belongs_to_open_conversation(
        conversation.last_message_at, received_at, timeout_minutes
    ):
        conversation.status = ConversationStatus.CLOSED
        conversation.closed_at = conversation.last_message_at
        conversation.close_reason = "inactivity"
        conversation = None

    if command in {"done", "new_report"}:
        session.add(
            InboundMessageReceipt(
                company_id=channel.company_id,
                provider_message_id=provider_message_id,
                disposition=f"command_{command}",
                received_at=received_at,
            )
        )
        session.flush()
        if conversation:
            conversation.status = ConversationStatus.CLOSED
            conversation.closed_at = received_at
            conversation.close_reason = command
        session.add(
            AuditEvent(
                company_id=channel.company_id,
                event_type=f"conversation.{command}",
                actor_type="employee",
                actor_reference=employee.employee_code,
                metadata_json={"provider_message_id": provider_message_id},
            )
        )
        return IngestionResult("conversation_closed", conversation_id=conversation.id if conversation else None)

    if conversation is None:
        conversation = FieldConversation(
            company_id=channel.company_id,
            employee_id=employee.id,
            started_at=received_at,
            last_message_at=received_at,
            employee_context=_employee_snapshot(employee),
        )
        session.add(conversation)
        session.flush()
    else:
        conversation.last_message_at = max(utc_aware(conversation.last_message_at), utc_aware(received_at))

    stored = FieldMessage(
        company_id=channel.company_id,
        conversation_id=conversation.id,
        employee_id=employee.id,
        provider_message_id=provider_message_id,
        message_type=message_type,
        text_content=text_content,
        provider_media_id=provider_media_id,
        provider_timestamp=received_at,
        raw_payload=message,
    )
    session.add(stored)
    session.add(
        InboundMessageReceipt(
            company_id=channel.company_id,
            provider_message_id=provider_message_id,
            disposition="accepted",
            received_at=received_at,
        )
    )
    session.flush()

    if provider_media_id:
        session.add(
            MediaAsset(
                company_id=channel.company_id,
                message_id=stored.id,
                provider_media_id=provider_media_id,
            )
        )
    return IngestionResult("accepted", stored.id, conversation.id)


def ingest_whatsapp_payload(session: Session, payload: dict[str, Any], timeout_minutes: int) -> list[IngestionResult]:
    results: list[IngestionResult] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = str(value.get("metadata", {}).get("phone_number_id", ""))
            for message in value.get("messages", []):
                results.append(
                    ingest_whatsapp_message(
                        session,
                        phone_number_id=phone_number_id,
                        message=message,
                        timeout_minutes=timeout_minutes,
                    )
                )
    return results
