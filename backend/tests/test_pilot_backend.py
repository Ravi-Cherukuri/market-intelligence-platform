"""Acceptance tests for the foundation of field-intelligence ingestion.

The fixtures model Meta webhook deliveries rather than calling private route
helpers. They make replay, sender privacy, conversation and company-boundary
requirements executable without a Meta account or paid AI calls.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import base64
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import pytest
import httpx
from openpyxl import Workbook
from openai.lib._pydantic import to_strict_json_schema

from app.domain.conversations import belongs_to_open_conversation, normalized_command
from app.domain.identity import InvalidPhoneNumber, normalize_indian_whatsapp_number
from app.domain.signals import EvidenceIdentity, classify_strength
from app.ai.model_router import ModelRouter, QualityTier, TaskType
from app.ai.schemas import ConversationExtraction, PriceObservation, WeeklyIntelligenceSynthesis
from app.models import (
    AuditEvent,
    BusinessScope,
    Company,
    ConversationStatus,
    Employee,
    EmploymentType,
    FieldConversation,
    FieldMessage,
    MediaAsset,
    MessageType,
    OutboundMessage,
    Observation,
    Product,
    ProductOwnership,
    CompetitionPrice,
    PriceType,
    Signal,
    SignalEvidence,
    SignalStrength,
    WeeklyBrief,
    WhatsAppChannel,
)
from app.security import verify_meta_signature
from app.services.imports import (
    MAX_IMPORT_COLUMNS,
    MAX_IMPORT_ROWS,
    commit_employees,
    commit_prices,
    preview_employees,
    preview_prices,
    read_tabular_upload,
)
from app.services.ingestion import ingest_whatsapp_message
from app.services.signals import _has_identity_anchor_overlap, _identity_anchors, reconcile_semantic_duplicates, upsert_signal
from app.services.weekly_intelligence import get_weekly_intelligence
from app.integrations.whatsapp import (
    DownloadedMedia,
    WhatsAppClient,
    WhatsAppMediaValidationError,
    validate_provider_sha256,
    validate_supported_media,
)
import app.integrations.whatsapp as whatsapp_integration
import app.worker as worker


BASE_TIME = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)


def epoch(value: datetime) -> str:
    return str(int(value.timestamp()))


def meta_message(
    *,
    message_id: str,
    sender: str = "9876543210",
    timestamp: datetime = BASE_TIME,
    text: str = "Competitor price increased in Maharashtra",
) -> dict[str, Any]:
    return {
        "id": message_id,
        "from": sender,
        "timestamp": epoch(timestamp),
        "type": "text",
        "text": {"body": text},
    }


def meta_payload(phone_number_id: str, message: dict[str, Any]) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "test-waba",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [message],
                        },
                    }
                ],
            }
        ],
    }


def signed_json(payload: dict[str, Any], secret: str = "test-app-secret") -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}


def seed_company(
    session: Session,
    *,
    name: str,
    phone_number_id: str,
    sender: str = "919876543210",
    employee_code: str = "EMP-001",
) -> tuple[Company, WhatsAppChannel, Employee]:
    company = Company(name=name)
    session.add(company)
    session.flush()
    channel = WhatsAppChannel(company_id=company.id, phone_number_id=phone_number_id)
    employee = Employee(
        company_id=company.id,
        employee_code=employee_code,
        employment_type=EmploymentType.FULL_TIME,
        state="Maharashtra",
        whatsapp_number=sender,
    )
    session.add_all([channel, employee])
    session.commit()
    return company, channel, employee


def test_identity_normalizes_common_indian_mobile_formats_and_rejects_invalid_values() -> None:
    assert normalize_indian_whatsapp_number("98765 43210") == "919876543210"
    assert normalize_indian_whatsapp_number("+91-98765-43210") == "919876543210"
    assert normalize_indian_whatsapp_number("919876543210") == "919876543210"

    for invalid in ("", "0000000000", "12345", "1234567890", "1234567890123456"):
        try:
            normalize_indian_whatsapp_number(invalid)
        except InvalidPhoneNumber:
            pass
        else:  # pragma: no cover - explicit failure makes the policy obvious.
            raise AssertionError(f"expected {invalid!r} to be rejected")


def test_conversation_window_and_commands_are_intentionally_exact() -> None:
    assert belongs_to_open_conversation(BASE_TIME, BASE_TIME + timedelta(minutes=29, seconds=59), 30)
    assert not belongs_to_open_conversation(BASE_TIME, BASE_TIME + timedelta(minutes=30), 30)
    assert normalized_command("  DONE ") == "done"
    assert normalized_command("new   report") == "new_report"
    assert normalized_command("done, price is 100") is None


def test_signal_strength_requires_distinct_employees_not_message_volume() -> None:
    same_employee = [
        EvidenceIdentity("employee-a", "conversation-1"),
        EvidenceIdentity("employee-a", "conversation-1"),
        EvidenceIdentity("employee-a", "conversation-2"),
    ]
    assert classify_strength(same_employee) == ("weak", 1, 2)
    corroborated = same_employee + [EvidenceIdentity("employee-b", "conversation-3")]
    assert classify_strength(corroborated) == ("strong", 2, 3)


def test_meta_signature_requires_valid_sha256_signature() -> None:
    body = b'{"entry":[]}'
    signature = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    assert verify_meta_signature(body, signature, "test-app-secret")
    assert not verify_meta_signature(body, "sha256=deadbeef", "test-app-secret")
    assert not verify_meta_signature(body, signature, "other-secret")
    assert not verify_meta_signature(body, None, "test-app-secret")
    assert not verify_meta_signature(body, signature, "")


def test_meta_webhook_challenge_accepts_only_configured_token(client: TestClient) -> None:
    url = "/api/v1/webhooks/whatsapp"
    accepted = client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "test-verify-token", "hub.challenge": "challenge"})
    rejected = client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "challenge"})

    assert accepted.status_code == 200
    assert accepted.text == "challenge"
    assert rejected.status_code == 403


def test_rejects_invalid_signature_without_persisting_content(client: TestClient, db_session: Session) -> None:
    seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    body = json.dumps(meta_payload("channel-one", meta_message(message_id="wamid-invalid-signature"))).encode()

    response = client.post(
        "/api/v1/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=not-valid", "Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert db_session.scalar(select(func.count()).select_from(FieldMessage)) == 0
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_authenticated_webhook_is_idempotent_across_meta_retries(client: TestClient, db_session: Session) -> None:
    seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    body, headers = signed_json(meta_payload("channel-one", meta_message(message_id="wamid-retry")))

    first = client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)
    second = client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)

    assert first.status_code == 200
    assert first.json()["messages_persisted"] == 1
    assert second.status_code == 200
    assert second.json()["messages_persisted"] == 0
    assert db_session.scalar(select(func.count()).select_from(FieldMessage)) == 1
    assert db_session.scalar(select(func.count()).select_from(FieldConversation)) == 1


def test_document_attachment_is_rejected_without_creating_media_work(db_session: Session) -> None:
    _, channel, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    document = {
        "id": "wamid-document",
        "from": "9876543210",
        "timestamp": epoch(BASE_TIME),
        "type": "document",
        "document": {"id": "provider-document-id", "filename": "price-list.xlsx"},
    }

    result = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message=document,
        timeout_minutes=30,
    )
    db_session.commit()
    assert result.status == "unsupported"
    assert db_session.scalar(
        select(FieldMessage).where(FieldMessage.provider_message_id == "wamid-document")
    ) is None
    assert db_session.scalar(select(func.count()).select_from(FieldConversation)) == 0
    assert db_session.scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert db_session.scalar(select(func.count()).select_from(OutboundMessage)) == 1


def test_unsupported_attachment_does_not_extend_an_existing_conversation(db_session: Session) -> None:
    _, channel, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    accepted = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message=meta_message(message_id="wamid-before-document"),
        timeout_minutes=30,
    )
    db_session.commit()
    conversation = db_session.get(FieldConversation, accepted.conversation_id)
    assert conversation is not None
    original_last_message_at = conversation.last_message_at

    result = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message={
            "id": "wamid-document-after-text",
            "from": "9876543210",
            "timestamp": epoch(BASE_TIME + timedelta(minutes=10)),
            "type": "document",
            "document": {"id": "provider-document-id"},
        },
        timeout_minutes=30,
    )
    db_session.commit()
    db_session.refresh(conversation)

    assert result.status == "unsupported"
    assert conversation.last_message_at == original_last_message_at
    assert db_session.scalar(select(func.count()).select_from(FieldMessage)) == 1


@pytest.mark.parametrize(
    ("content", "mime_type"),
    [
        (b"\xff\xd8\xffphoto", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\nphoto", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPphoto", "image/webp"),
        (b"OggSvoice", "audio/ogg; codecs=opus"),
        (b"\x00\x00\x00\x18ftypM4A ", "audio/mp4"),
    ],
)
def test_media_signature_validation_accepts_only_matching_voice_and_photo_types(
    content: bytes, mime_type: str
) -> None:
    assert validate_supported_media(content, mime_type) == mime_type.split(";", 1)[0]


@pytest.mark.parametrize(
    ("content", "mime_type"),
    [
        (b"PK\x03\x04spreadsheet", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (b"not-a-jpeg", "image/jpeg"),
        (b"\xff\xd8\xffphoto", "audio/ogg"),
    ],
)
def test_media_signature_validation_rejects_unsupported_or_mismatched_content(
    content: bytes, mime_type: str
) -> None:
    with pytest.raises(WhatsAppMediaValidationError):
        validate_supported_media(content, mime_type)


def test_provider_media_checksum_accepts_hex_and_base64_and_rejects_mismatch() -> None:
    content = b"OggSverified voice note"
    digest = hashlib.sha256(content).digest()
    validate_provider_sha256(content, digest.hex())
    validate_provider_sha256(content, base64.b64encode(digest).decode("ascii"))
    with pytest.raises(WhatsAppMediaValidationError):
        validate_provider_sha256(content, "0" * 64)


def test_whatsapp_download_streams_and_verifies_provider_media(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"OggSverified download"
    digest = hashlib.sha256(content).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.facebook.com":
            return httpx.Response(
                200,
                json={
                    "url": "https://media.example/voice",
                    "file_size": len(content),
                    "mime_type": "audio/ogg",
                    "sha256": digest,
                },
            )
        return httpx.Response(200, content=content, headers={"content-type": "audio/ogg"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        whatsapp_integration.httpx,
        "Client",
        lambda **_: real_client(transport=transport),
    )
    downloaded = WhatsAppClient(
        base_url="https://graph.facebook.com", api_version="v99.0", access_token="test-token"
    ).download_media("media-id")

    assert downloaded.content == content
    assert downloaded.mime_type == "audio/ogg"
    assert downloaded.provider_sha256 == digest


def test_whatsapp_download_rejects_declared_oversize_media(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={"url": "https://media.example/huge", "file_size": 26_000_000, "mime_type": "audio/ogg"},
        )
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        whatsapp_integration.httpx,
        "Client",
        lambda **_: real_client(transport=transport),
    )
    client = WhatsAppClient(
        base_url="https://graph.facebook.com", api_version="v99.0", access_token="test-token"
    )
    with pytest.raises(WhatsAppMediaValidationError, match="size limit"):
        client.download_media("media-id")


@pytest.mark.parametrize("media_type", ["audio", "image"])
def test_media_without_provider_id_is_audited_without_opening_conversation(
    db_session: Session, media_type: str
) -> None:
    _, channel, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    result = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message={
            "id": f"wamid-missing-{media_type}-id",
            "from": "9876543210",
            "timestamp": epoch(BASE_TIME),
            "type": media_type,
            media_type: {},
        },
        timeout_minutes=30,
    )
    db_session.commit()

    assert result.status == "malformed_media"
    assert db_session.scalar(select(func.count()).select_from(FieldConversation)) == 0
    assert db_session.scalar(select(func.count()).select_from(FieldMessage)) == 0
    assert db_session.scalar(select(func.count()).select_from(MediaAsset)) == 0


@pytest.mark.parametrize(
    ("media_type", "mime_type"),
    [("audio", "audio/ogg"), ("image", "image/jpeg")],
)
def test_pilot_media_is_stored_as_unscanned_without_local_decoding(
    db_session: Session,
    session_factory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
    media_type: str,
    mime_type: str,
) -> None:
    """The 2 GiB pilot may retain voice/photos, but must not run ClamAV or AI.

    This uses fake provider and S3 boundaries: no external API call or AWS
    credential lookup is permitted during the worker test.
    """
    company, channel, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    provider_media_id = f"provider-{media_type}-id"
    result = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message={
            "id": f"wamid-{media_type}",
            "from": "9876543210",
            "timestamp": epoch(BASE_TIME),
            "type": media_type,
            media_type: {"id": provider_media_id},
        },
        timeout_minutes=30,
    )
    db_session.commit()
    assert result.status == "accepted"
    asset_id = db_session.scalar(select(MediaAsset.id).where(MediaAsset.provider_media_id == provider_media_id))
    assert asset_id is not None

    stored: dict[str, object] = {}

    class FakeWhatsAppClient:
        def __init__(self, **_: object) -> None:
            pass

        def download_media(self, media_id: str) -> DownloadedMedia:
            assert media_id == provider_media_id
            return DownloadedMedia(content=b"safe pilot media", mime_type=mime_type, provider_sha256=None)

    class FakeMediaStore:
        def __init__(self, bucket: str, region: str) -> None:
            stored["bucket"] = bucket
            stored["region"] = region

        def put_inbound_media(self, **kwargs: object) -> tuple[str, str]:
            stored.update(kwargs)
            return f"companies/{company.id}/inbound/test/{provider_media_id}", "test-digest"

    class NoAiClient:
        def __init__(self, *_: object) -> None:
            raise AssertionError("AI must not run when OPENAI_API_KEY is absent")

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(worker, "WhatsAppClient", FakeWhatsAppClient)
    monkeypatch.setattr(worker, "S3MediaStore", FakeMediaStore)
    monkeypatch.setattr(worker, "OpenAIIntelligenceClient", NoAiClient)

    assert worker.process_media_assets() == 1
    db_session.expire_all()
    asset = db_session.get(MediaAsset, asset_id)
    message = db_session.get(FieldMessage, result.message_id)
    assert asset is not None
    assert asset.scan_status == "accepted_unscanned_pilot"
    assert asset.analysis_status == "waiting"
    assert asset.object_key == f"companies/{company.id}/inbound/test/{provider_media_id}"
    assert asset.mime_type == mime_type
    assert asset.sha256 == "test-digest"
    assert message is not None
    assert message.derived_text is None
    assert stored["company_id"] == company.id
    assert stored["media_id"] == provider_media_id
    assert stored["content"] == b"safe pilot media"


def test_invalid_provider_media_is_terminal_and_unblocks_closed_conversation(
    db_session: Session,
    session_factory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, channel, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    result = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message={
            "id": "wamid-invalid-media",
            "from": "9876543210",
            "timestamp": epoch(BASE_TIME),
            "type": "image",
            "image": {"id": "invalid-provider-media"},
        },
        timeout_minutes=30,
    )
    conversation = db_session.get(FieldConversation, result.conversation_id)
    assert conversation is not None
    conversation.status = ConversationStatus.CLOSED
    conversation.closed_at = BASE_TIME
    conversation.analysis_status = "awaiting_media"
    db_session.commit()

    class InvalidMediaClient:
        def __init__(self, **_: object) -> None:
            pass

        def download_media(self, _: str) -> DownloadedMedia:
            raise WhatsAppMediaValidationError("checksum mismatch")

    class UnusedMediaStore:
        def __init__(self, *_: object) -> None:
            pass

        def put_inbound_media(self, **_: object) -> tuple[str, str]:
            raise AssertionError("Rejected media must never reach object storage")

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    monkeypatch.setattr(worker, "WhatsAppClient", InvalidMediaClient)
    monkeypatch.setattr(worker, "S3MediaStore", UnusedMediaStore)

    assert worker.process_media_assets() == 1
    db_session.expire_all()
    asset = db_session.scalar(select(MediaAsset).where(MediaAsset.provider_media_id == "invalid-provider-media"))
    message = db_session.get(FieldMessage, result.message_id)
    conversation = db_session.get(FieldConversation, result.conversation_id)
    assert asset is not None
    assert asset.scan_status == "rejected_invalid_media"
    assert asset.analysis_status == "blocked"
    assert message is not None and message.derived_text == "[invalid media omitted]"
    assert conversation is not None and conversation.analysis_status == "waiting"


def test_unknown_sender_discards_message_and_media_but_keeps_minimal_audit_event(
    client: TestClient, db_session: Session
) -> None:
    company, _, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    field_content = "Private field observation that must never be retained"
    payload = meta_payload(
        "channel-one",
        meta_message(message_id="wamid-unknown", sender="9123456789", text=field_content),
    )
    body, headers = signed_json(payload)

    response = client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)
    audit = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "whatsapp.unregistered_sender"))

    assert response.status_code == 200
    assert response.json()["messages_persisted"] == 0
    assert db_session.scalar(select(func.count()).select_from(FieldMessage)) == 0
    assert audit is not None
    assert audit.company_id == company.id
    assert audit.actor_reference != "9123456789"
    assert field_content not in json.dumps(audit.metadata_json)
    assert db_session.scalar(select(func.count()).select_from(OutboundMessage)) == 1


def test_destination_number_segregates_same_sender_between_companies(client: TestClient, db_session: Session) -> None:
    company_a, _, employee_a = seed_company(
        db_session, name="Company A", phone_number_id="channel-a", employee_code="A-001"
    )
    company_b, _, employee_b = seed_company(
        db_session, name="Company B", phone_number_id="channel-b", employee_code="B-001"
    )
    assert employee_a.whatsapp_number == employee_b.whatsapp_number

    body_a, headers_a = signed_json(meta_payload("channel-a", meta_message(message_id="wamid-a")))
    body_b, headers_b = signed_json(meta_payload("channel-b", meta_message(message_id="wamid-b")))
    assert client.post("/api/v1/webhooks/whatsapp", content=body_a, headers=headers_a).status_code == 200
    assert client.post("/api/v1/webhooks/whatsapp", content=body_b, headers=headers_b).status_code == 200

    messages = db_session.scalars(select(FieldMessage).order_by(FieldMessage.provider_message_id)).all()
    conversations = db_session.scalars(select(FieldConversation).order_by(FieldConversation.company_id)).all()
    assert [(message.company_id, message.employee_id) for message in messages] == [
        (company_a.id, employee_a.id),
        (company_b.id, employee_b.id),
    ]
    assert {conversation.company_id for conversation in conversations} == {company_a.id, company_b.id}
    conversations_by_id = {conversation.id: conversation for conversation in conversations}
    assert all(
        message.company_id == conversations_by_id[message.conversation_id].company_id
        for message in messages
    )


def test_inactivity_boundary_and_done_close_a_conversation(db_session: Session) -> None:
    company, channel, employee = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    first = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message=meta_message(message_id="wamid-first", timestamp=BASE_TIME),
        timeout_minutes=30,
    )
    second = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message=meta_message(message_id="wamid-before-boundary", timestamp=BASE_TIME + timedelta(minutes=29, seconds=59)),
        timeout_minutes=30,
    )
    exact_boundary = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message=meta_message(message_id="wamid-boundary", timestamp=BASE_TIME + timedelta(minutes=59, seconds=59)),
        timeout_minutes=30,
    )
    done = ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message=meta_message(message_id="wamid-done", timestamp=BASE_TIME + timedelta(minutes=60), text="Done"),
        timeout_minutes=30,
    )
    db_session.commit()

    first_conversation = db_session.get(FieldConversation, first.conversation_id)
    second_conversation = db_session.get(FieldConversation, exact_boundary.conversation_id)
    assert first.conversation_id == second.conversation_id
    assert exact_boundary.conversation_id != first.conversation_id
    assert first_conversation.status == ConversationStatus.CLOSED
    assert first_conversation.close_reason == "inactivity"
    assert second_conversation.status == ConversationStatus.CLOSED
    assert second_conversation.close_reason == "done"
    assert done.status == "conversation_closed"
    assert db_session.scalar(select(func.count()).select_from(FieldMessage)) == 3
    assert db_session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.company_id == company.id)) == 1
    assert employee.id == second_conversation.employee_id


def test_done_command_delivery_is_idempotent(db_session: Session) -> None:
    """Meta can retry a command delivery just like an evidence message.

    A retry may not add a second audit event or cause a second state transition.
    """
    company, channel, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    ingest_whatsapp_message(
        db_session,
        phone_number_id=channel.phone_number_id,
        message=meta_message(message_id="wamid-open", timestamp=BASE_TIME),
        timeout_minutes=30,
    )
    done_message = meta_message(message_id="wamid-done-retry", timestamp=BASE_TIME + timedelta(minutes=1), text="Done")
    first = ingest_whatsapp_message(
        db_session, phone_number_id=channel.phone_number_id, message=done_message, timeout_minutes=30
    )
    # The production webhook commits one delivery before Meta can retry it.
    db_session.commit()
    second = ingest_whatsapp_message(
        db_session, phone_number_id=channel.phone_number_id, message=done_message, timeout_minutes=30
    )
    db_session.commit()

    assert first.status == "conversation_closed"
    assert second.status == "duplicate"
    assert db_session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.company_id == company.id,
            AuditEvent.event_type == "conversation.done",
        )
    ) == 1


def test_employee_import_preview_reports_errors_and_never_partially_commits(db_session: Session) -> None:
    company, _, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    preview = preview_employees(
        [
            {
                "Employee Code": "EMP-NEW",
                "Employment Type": "Full Time",
                "State": "Maharashtra",
                "WhatsApp Phone Number": "9876543210",
            },
            {
                "Employee Code": "EMP-NEW",
                "Employment Type": "incorrect type",
                "State": "",
                "WhatsApp Phone Number": "12345",
            },
        ]
    )

    assert not preview.as_dict()["valid"]
    assert {error.field for error in preview.errors} >= {"employee_code", "employment_type", "state", "whatsapp_number"}
    try:
        commit_employees(db_session, company.id, preview)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid preview must not be commit-able")
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 1


def test_employee_master_api_previews_then_atomically_commits(
    client: TestClient, db_session: Session
) -> None:
    company = Company(name="Pilot Imports")
    db_session.add(company)
    db_session.commit()
    content = (
        "employee_code,employment_type,designation,territory_code,state,email,whatsapp_number,active\n"
        "EMP-101,full_time,Field Officer,FOT-MH-01,Maharashtra,,9876543210,true\n"
        "EMP-102,contractual,Field Associate,FOT-GJ-02,Gujarat,field@example.com,+91 91234 56789,true\n"
    ).encode()
    endpoint = f"/api/v1/admin/companies/{company.id}/masters/employees"

    preview_response = client.post(
        f"{endpoint}/preview",
        files={"file": ("employees.csv", content, "text/csv")},
        auth=("Admin", "Password"),
    )
    assert preview_response.status_code == 200
    assert preview_response.json()["valid"] is True
    assert preview_response.json()["row_count"] == 2
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 0

    commit_response = client.post(
        f"{endpoint}/commit",
        files={"file": ("employees.csv", content, "text/csv")},
        auth=("Admin", "Password"),
    )
    assert commit_response.status_code == 200
    assert commit_response.json() == {"valid": True, "committed": 2, "errors": []}
    employees = db_session.scalars(select(Employee).order_by(Employee.employee_code)).all()
    assert [employee.employee_code for employee in employees] == ["EMP-101", "EMP-102"]
    assert [employee.whatsapp_number for employee in employees] == ["919876543210", "919123456789"]


def xlsx_without_dimension(rows: list[list[Any]], *, sparse_cell: tuple[int, int, Any] | None = None) -> bytes:
    source = io.BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    if sparse_cell is not None:
        sheet.cell(*sparse_cell)
    workbook.save(source)

    rewritten = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source.getvalue())) as archive, zipfile.ZipFile(rewritten, "w") as output:
        for item in archive.infolist():
            payload = archive.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                payload = re.sub(rb"<dimension[^>]*/>", b"", payload)
            output.writestr(item, payload)
    return rewritten.getvalue()


def test_employee_master_accepts_xlsx_without_optional_dimension_cache() -> None:
    """Streaming spreadsheet writers may omit worksheet dimension metadata."""
    content = xlsx_without_dimension(
        [
            ["employee_code", "employment_type", "state", "whatsapp_number"],
            ["PILOT001", "full_time", "Maharashtra", "+919820631696"],
        ]
    )

    rows = read_tabular_upload("employees.xlsx", content)
    assert rows == [
        {
            "employee_code": "PILOT001",
            "employment_type": "full_time",
            "state": "Maharashtra",
            "whatsapp_number": "+919820631696",
        }
    ]


def test_employee_master_accepts_empty_dimensionless_xlsx() -> None:
    assert read_tabular_upload("employees.xlsx", xlsx_without_dimension([])) == []


def test_employee_master_bounds_dimensionless_sparse_xlsx_iteration() -> None:
    content = xlsx_without_dimension(
        [["employee_code", "employment_type", "state", "whatsapp_number"]],
        sparse_cell=(1_048_576, 1, "late-value"),
    )
    with pytest.raises(ValueError, match=f"at most {MAX_IMPORT_ROWS} data rows"):
        read_tabular_upload("employees.xlsx", content)


def test_employee_master_rejects_dimensionless_xlsx_wider_than_column_limit() -> None:
    content = xlsx_without_dimension([[f"column_{index}" for index in range(MAX_IMPORT_COLUMNS + 1)]])
    with pytest.raises(ValueError, match=f"at most {MAX_IMPORT_COLUMNS} columns"):
        read_tabular_upload("employees.xlsx", content)


def test_employee_master_rejects_dimensionless_xlsx_data_wider_than_header() -> None:
    content = xlsx_without_dimension(
        [
            ["employee_code", "employment_type", "state", "whatsapp_number"],
            ["PILOT001", "full_time", "Maharashtra", "+919820631696", "unexpected"],
        ]
    )
    with pytest.raises(ValueError, match="more values than the header"):
        read_tabular_upload("employees.xlsx", content)


def test_employee_master_api_rejects_empty_file_without_writes(
    client: TestClient, db_session: Session
) -> None:
    company = Company(name="Pilot Empty Import")
    db_session.add(company)
    db_session.commit()
    response = client.post(
        f"/api/v1/admin/companies/{company.id}/masters/employees/commit",
        files={"file": ("employees.csv", b"employee_code,state,whatsapp_number\n", "text/csv")},
        auth=("Admin", "Password"),
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["errors"] == [
        {"row": 1, "field": "file", "message": "The employee master contains no data rows"}
    ]
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 0


def test_employee_master_api_requires_pilot_administrator_credentials(
    client: TestClient, db_session: Session
) -> None:
    company = Company(name="Pilot Protected Import")
    db_session.add(company)
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/companies/{company.id}/masters/employees/preview",
        files={"file": ("employees.csv", b"employee_code\nEMP-101\n", "text/csv")},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 0


def test_employee_master_api_rejects_unknown_company_before_parsing_or_writing(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/api/v1/admin/companies/not-a-company/masters/employees/preview",
        files={"file": ("employees.csv", b"employee_code\nEMP-101\n", "text/csv")},
        auth=("Admin", "Password"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Company not found"
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 0


def test_employee_master_api_rejects_wrong_file_type_and_oversized_file_without_writes(
    client: TestClient, db_session: Session
) -> None:
    company = Company(name="Pilot Upload Bounds")
    db_session.add(company)
    db_session.commit()
    endpoint = f"/api/v1/admin/companies/{company.id}/masters/employees/preview"

    wrong_type = client.post(
        endpoint,
        files={"file": ("employees.txt", b"not a master", "text/plain")},
        auth=("Admin", "Password"),
    )
    oversized = client.post(
        endpoint,
        files={"file": ("employees.csv", b"x" * 10_000_001, "text/csv")},
        auth=("Admin", "Password"),
    )

    assert wrong_type.status_code == 422
    assert wrong_type.json()["detail"] == "Upload a CSV or XLSX file"
    assert oversized.status_code == 413
    assert oversized.json()["detail"] == "Master file exceeds 10 MB"
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 0


def test_employee_master_commit_rolls_back_every_row_on_existing_phone_conflict(
    client: TestClient, db_session: Session
) -> None:
    company = Company(name="Pilot Atomic Commit")
    db_session.add(company)
    db_session.flush()
    db_session.add(
        Employee(
            company_id=company.id,
            employee_code="EMP-EXISTING",
            employment_type=EmploymentType.FULL_TIME,
            state="Maharashtra",
            whatsapp_number="919876543210",
        )
    )
    db_session.commit()
    content = (
        "employee_code,employment_type,state,whatsapp_number\n"
        "EMP-NEW,full_time,Maharashtra,9123456789\n"
        "EMP-CONFLICT,contractual,Maharashtra,9876543210\n"
    ).encode()

    response = client.post(
        f"/api/v1/admin/companies/{company.id}/masters/employees/commit",
        files={"file": ("employees.csv", content, "text/csv")},
        auth=("Admin", "Password"),
    )

    assert response.status_code == 409
    assert "WhatsApp number already belongs to active employee EMP-EXISTING" in response.json()["detail"]
    assert db_session.scalars(select(Employee).order_by(Employee.employee_code)).all()[0].employee_code == "EMP-EXISTING"
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 1


def test_employee_master_allows_number_reassignment_after_employee_is_inactive(db_session: Session) -> None:
    company, _, former = seed_company(db_session, name="Pilot Reassignment", phone_number_id="reassign-channel")
    former.active = False
    db_session.commit()
    preview = preview_employees(
        [
            {
                "employee_code": "EMP-NEW",
                "employment_type": "full_time",
                "state": "Maharashtra",
                "whatsapp_number": former.whatsapp_number,
            }
        ]
    )
    assert preview.as_dict()["valid"] is True
    assert commit_employees(db_session, company.id, preview) == 1
    db_session.commit()
    mappings = db_session.scalars(
        select(Employee).where(Employee.company_id == company.id, Employee.whatsapp_number == former.whatsapp_number)
    ).all()
    assert len(mappings) == 2
    assert sum(employee.active for employee in mappings) == 1


def test_employee_master_api_returns_422_for_csv_rows_wider_than_header(
    client: TestClient, db_session: Session
) -> None:
    company = Company(name="Pilot Malformed CSV")
    db_session.add(company)
    db_session.commit()
    response = client.post(
        f"/api/v1/admin/companies/{company.id}/masters/employees/preview",
        files={
            "file": (
                "employees.csv",
                b"employee_code,state,whatsapp_number\nEMP-1,Maharashtra,9876543210,unexpected\n",
                "text/csv",
            )
        },
        auth=("Admin", "Password"),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "The uploaded file could not be parsed"
    assert db_session.scalar(select(func.count()).select_from(Employee)) == 0


def test_price_import_is_append_only_and_requires_known_competitor_product(db_session: Session) -> None:
    company, _, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    product = Product(
        company_id=company.id,
        ownership=ProductOwnership.COMPETITOR,
        brand="RivalShield",
        category="fungicide",
    )
    db_session.add(product)
    db_session.commit()
    rows = [
        {
            "Brand": "RivalShield",
            "State": "Maharashtra",
            "Pack Size": "250 ml",
            "Price Type": "Farmer Price",
            "Amount": "540.00",
            "Effective Date": "2026-08-01T00:00:00+00:00",
        }
    ]
    preview = preview_prices(db_session, company.id, rows)
    assert preview.as_dict()["valid"]
    assert commit_prices(db_session, company.id, preview) == 1
    assert commit_prices(db_session, company.id, preview) == 1
    db_session.commit()
    prices = db_session.scalars(select(CompetitionPrice).where(CompetitionPrice.product_id == product.id)).all()
    assert len(prices) == 2
    assert {price.price_type.value for price in prices} == {"farmer_price"}
    assert all(price.source == "initial_upload" for price in prices)

    missing_product = preview_prices(
        db_session,
        company.id,
        [{**rows[0], "Brand": "Unknown competitor"}],
    )
    assert any(error.field == "brand" for error in missing_product.errors)


def test_price_import_rejects_invalid_effective_date_instead_of_inventing_history(db_session: Session) -> None:
    company, _, _ = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    db_session.add(
        Product(
            company_id=company.id,
            ownership=ProductOwnership.COMPETITOR,
            brand="RivalShield",
            category="fungicide",
        )
    )
    db_session.commit()
    preview = preview_prices(
        db_session,
        company.id,
        [
            {
                "Brand": "RivalShield",
                "State": "Maharashtra",
                "Pack Size": "250 ml",
                "Price Type": "Farmer Price",
                "Amount": "540.00",
                "Effective Date": "not-a-date",
            }
        ],
    )
    assert any(error.field == "observed_at" for error in preview.errors)


def test_model_router_uses_task_quality_thresholds_and_explicit_tiers() -> None:
    router = ModelRouter()
    assert router.route(TaskType.EXTRACTION, QualityTier.AUTO).model == "gpt-5.6-terra"
    assert router.route(TaskType.REPORT_SYNTHESIS, QualityTier.AUTO).model == "gpt-5.6"
    assert router.route(TaskType.REPORT_SYNTHESIS, QualityTier.ECONOMY).model == "gpt-5.6-terra"
    assert router.route(TaskType.CONVERSATIONAL_ANALYSIS, QualityTier.PREMIUM).model == "gpt-5.6"
    assert router.route(TaskType.TRANSCRIPTION, QualityTier.AUTO).model == "gpt-4o-mini-transcribe"
    assert router.upgrade(router.route(TaskType.EXTRACTION), TaskType.EXTRACTION).model == "gpt-5.6"


def test_conversation_extraction_schema_avoids_unsupported_regex_lookaround() -> None:
    """Keep the schema compatible with OpenAI Structured Outputs."""

    strict_schema = to_strict_json_schema(ConversationExtraction)
    encoded_schema = json.dumps(strict_schema)
    assert "(?=" not in encoded_schema
    assert "(?!" not in encoded_schema
    assert "(?<=" not in encoded_schema
    assert "(?<!" not in encoded_schema
    assert strict_schema["$defs"]["PriceObservation"]["properties"]["amount"] == {
        "anyOf": [
            {
                "exclusiveMinimum": 0,
                "maximum": 999_999_999_999.99,
                "multipleOf": 0.01,
                "type": "number",
            },
            {"type": "null"},
        ],
        "title": "Amount",
    }


@pytest.mark.parametrize("amount", [0, 540.001, 1_000_000_000_000, float("inf"), float("nan")])
def test_price_observation_rejects_values_that_cannot_be_persisted(amount: float) -> None:
    with pytest.raises(ValueError):
        PriceObservation(original_product_text="Synthetic product", amount=amount)


@pytest.mark.parametrize("amount", [0.01, 540.1, 999_999_999_999.99])
def test_price_observation_accepts_persistable_currency_values(amount: float) -> None:
    parsed = PriceObservation(original_product_text="Synthetic product", amount=amount)
    assert parsed.amount == amount


def test_signal_becomes_strong_only_with_independent_employee_evidence_and_appends_price(
    db_session: Session,
) -> None:
    company, _, employee_one = seed_company(db_session, name="Pilot", phone_number_id="channel-one")
    employee_two = Employee(
        company_id=company.id,
        employee_code="EMP-002",
        employment_type=EmploymentType.CONTRACTUAL,
        state="Maharashtra",
        whatsapp_number="919876543211",
    )
    db_session.add(employee_two)
    db_session.flush()
    first_conversation = FieldConversation(
        company_id=company.id,
        employee_id=employee_one.id,
        started_at=BASE_TIME,
        last_message_at=BASE_TIME,
        employee_context={"state": "Maharashtra"},
    )
    second_conversation = FieldConversation(
        company_id=company.id,
        employee_id=employee_two.id,
        started_at=BASE_TIME,
        last_message_at=BASE_TIME,
        employee_context={"state": "Maharashtra"},
    )
    product = Product(
        company_id=company.id,
        ownership=ProductOwnership.COMPETITOR,
        brand="RivalShield",
        category="fungicide",
    )
    db_session.add_all([first_conversation, second_conversation, product])
    db_session.flush()

    def observation(employee_id: str, conversation_id: str, message_id: str) -> Observation:
        return Observation(
            company_id=company.id,
            employee_id=employee_id,
            conversation_id=conversation_id,
            state="Maharashtra",
            category="pricing_schemes",
            subject_key="rivalshield:250ml:farmer_price",
            claim="RivalShield farmer price is Rs 540 for 250 ml",
            structured_data={
                "price": {
                    "product_id": product.id,
                    "pack_size": "250 ml",
                    "price_type": "farmer_price",
                    "amount": 540.1,
                    "currency": "INR",
                }
            },
            confidence=Decimal("0.90"),
            source_message_ids=[message_id],
        )

    first_observation = observation(employee_one.id, first_conversation.id, "message-1")
    db_session.add(first_observation)
    db_session.flush()
    weak = upsert_signal(db_session, first_observation)
    db_session.flush()
    assert weak.strength == SignalStrength.WEAK
    assert db_session.scalar(select(func.count()).select_from(CompetitionPrice)) == 0

    second_observation = observation(employee_two.id, second_conversation.id, "message-2")
    db_session.add(second_observation)
    db_session.flush()
    strong = upsert_signal(db_session, second_observation)
    db_session.commit()

    assert strong.strength == SignalStrength.STRONG
    assert strong.distinct_employee_count == 2
    price = db_session.scalar(select(CompetitionPrice).where(CompetitionPrice.source == "strong_field_signal"))
    assert price is not None
    assert price.amount == Decimal("540.10")
    assert set(price.evidence_ids) == {first_observation.id, second_observation.id}


class FakeSemanticMatcher:
    """A deterministic stand-in for the probabilistic provider decision."""

    def __init__(self, *, confidence: float, select_candidate: bool = True) -> None:
        self.confidence = confidence
        self.select_candidate = select_candidate
        self.calls: list[tuple[dict[str, object], list[dict[str, object]]]] = []

    def match_signal(self, *, proposed: dict[str, object], candidates: list[dict[str, object]]):
        self.calls.append((proposed, candidates))
        return SimpleNamespace(
            decision=SimpleNamespace(
                candidate_signal_id=str(candidates[0]["id"]) if self.select_candidate else None,
                confidence=self.confidence,
                canonical_subject_key="bayer soybean 3-way mix herbicide",
                rationale="Same Bayer soybean herbicide launch in Ahilyanagar.",
            ),
            profile=SimpleNamespace(provider="openai", model="test-semantic-model"),
            input_tokens=17,
            output_tokens=9,
            latency_ms=12,
        )


def test_semantically_equivalent_signals_become_strong_with_high_confidence_matcher(db_session: Session) -> None:
    company, _, employee_one = seed_company(db_session, name="Semantic Pilot", phone_number_id="semantic-channel")
    employee_two = Employee(
        company_id=company.id,
        employee_code="EMP-002",
        employment_type=EmploymentType.CONTRACTUAL,
        state="Maharashtra",
        whatsapp_number="919876543211",
    )
    db_session.add(employee_two)
    db_session.flush()
    conversations = [
        FieldConversation(
            company_id=company.id,
            employee_id=employee_one.id,
            started_at=BASE_TIME,
            last_message_at=BASE_TIME,
            employee_context={"state": "Maharashtra"},
        ),
        FieldConversation(
            company_id=company.id,
            employee_id=employee_two.id,
            started_at=BASE_TIME,
            last_message_at=BASE_TIME,
            employee_context={"state": "Maharashtra"},
        ),
    ]
    db_session.add_all(conversations)
    db_session.flush()

    first = Observation(
        company_id=company.id,
        employee_id=employee_one.id,
        conversation_id=conversations[0].id,
        state="Maharashtra",
        category="new_launches",
        subject_key="bayer soybean 3-way mix herbicide",
        claim="Bayer is launching a soybean 3-way mix herbicide in Ahilyanagar at about Rs 950 per acre.",
        structured_data={"mentioned_crops": ["soybean"]},
        confidence=Decimal("0.90"),
        source_message_ids=["message-1"],
    )
    second = Observation(
        company_id=company.id,
        employee_id=employee_two.id,
        conversation_id=conversations[1].id,
        state="Maharashtra",
        category="new_launches",
        subject_key="bayer soybean three-way mix herbicide",
        claim="A Bayer soybean three-way-mix herbicide is new in Ahilyanagar, priced around Rs 900 to 1,000 per acre.",
        structured_data={"mentioned_crops": ["soybean"]},
        confidence=Decimal("0.90"),
        source_message_ids=["message-2"],
    )
    db_session.add(first)
    db_session.flush()
    initial = upsert_signal(db_session, first)
    db_session.add(second)
    db_session.flush()
    matcher = FakeSemanticMatcher(confidence=0.91)
    matched = upsert_signal(db_session, second, semantic_matcher=matcher)
    db_session.commit()

    assert matched.id == initial.id
    assert matched.strength == SignalStrength.STRONG
    assert matched.distinct_employee_count == 2
    assert second.subject_key == "bayer soybean three-way mix herbicide"
    assert len(matcher.calls) == 1
    audit = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "signal.semantic_match"))
    assert audit is not None
    assert audit.metadata_json["accepted"] is True
    assert audit.metadata_json["confidence"] == 0.91


def test_signal_matching_never_combines_own_and_competitor_business_scopes(db_session: Session) -> None:
    company, _, employee_one = seed_company(db_session, name="Scope Pilot", phone_number_id="scope-channel")
    employee_two = Employee(
        company_id=company.id,
        employee_code="EMP-002",
        employment_type=EmploymentType.CONTRACTUAL,
        state="Maharashtra",
        whatsapp_number="919876543211",
    )
    db_session.add(employee_two)
    db_session.flush()
    conversations = [
        FieldConversation(
            company_id=company.id,
            employee_id=employee.id,
            started_at=BASE_TIME,
            last_message_at=BASE_TIME,
            employee_context={"state": "Maharashtra"},
        )
        for employee in (employee_one, employee_two)
    ]
    db_session.add_all(conversations)
    db_session.flush()
    observations = [
        Observation(
            company_id=company.id,
            employee_id=employee.id,
            conversation_id=conversation.id,
            state="Maharashtra",
            category="product_acceptance",
            business_scope=scope,
            subject_key="soybean herbicide acceptance",
            claim=claim,
            structured_data={},
            confidence=Decimal("0.90"),
            source_message_ids=[f"message-{index}"],
        )
        for index, (employee, conversation, scope, claim) in enumerate(
            (
                (employee_one, conversations[0], BusinessScope.OWN_BUSINESS, "Our soybean herbicide is gaining acceptance."),
                (employee_two, conversations[1], BusinessScope.COMPETITOR, "A competitor soybean herbicide is gaining acceptance."),
            ),
            start=1,
        )
    ]
    matcher = FakeSemanticMatcher(confidence=0.99)
    created_signals = []
    for observation in observations:
        db_session.add(observation)
        db_session.flush()
        created_signals.append(upsert_signal(db_session, observation, semantic_matcher=matcher))
    db_session.commit()

    assert created_signals[0].id != created_signals[1].id
    assert db_session.scalar(select(func.count()).select_from(Signal)) == 2
    assert matcher.calls == []


def test_identity_anchor_guard_accepts_three_way_variant_but_rejects_only_topical_similarity() -> None:
    candidate = SimpleNamespace(
        subject_key="bayer soybean three-way herbicide",
        title="Bayer soybean three-way herbicide launch",
        summary="Bayer soybean three-way herbicide launch in Ahilyanagar.",
    )
    proposed = {
        "subject_key": "bayer soybean 3-way herbicide",
        "claim": "Bayer soybean 3-way herbicide launch in Ahilyanagar.",
        "structured_data": {},
    }
    unrelated = {
        "subject_key": "rival cotton herbicide launch",
        "claim": "A rival herbicide is new for cotton.",
        "structured_data": {},
    }

    assert {"bayer", "soybean", "3"}.issubset(_identity_anchors(proposed["subject_key"]))
    assert _has_identity_anchor_overlap(proposed, candidate)
    assert not _has_identity_anchor_overlap(unrelated, candidate)


def test_semantic_matcher_does_not_merge_below_confidence_threshold(db_session: Session) -> None:
    company, _, employee_one = seed_company(db_session, name="Semantic Threshold", phone_number_id="threshold-channel")
    employee_two = Employee(
        company_id=company.id,
        employee_code="EMP-002",
        employment_type=EmploymentType.CONTRACTUAL,
        state="Maharashtra",
        whatsapp_number="919876543211",
    )
    db_session.add(employee_two)
    db_session.flush()
    first_conversation = FieldConversation(
        company_id=company.id,
        employee_id=employee_one.id,
        started_at=BASE_TIME,
        last_message_at=BASE_TIME,
        employee_context={"state": "Maharashtra"},
    )
    second_conversation = FieldConversation(
        company_id=company.id,
        employee_id=employee_two.id,
        started_at=BASE_TIME,
        last_message_at=BASE_TIME,
        employee_context={"state": "Maharashtra"},
    )
    db_session.add_all([first_conversation, second_conversation])
    db_session.flush()
    first = Observation(
        company_id=company.id,
        employee_id=employee_one.id,
        conversation_id=first_conversation.id,
        state="Maharashtra",
        category="new_launches",
        subject_key="bayer soybean 3-way mix herbicide",
        claim="Bayer soybean herbicide launch.",
        structured_data={},
        confidence=Decimal("0.90"),
        source_message_ids=["message-1"],
    )
    second = Observation(
        company_id=company.id,
        employee_id=employee_two.id,
        conversation_id=second_conversation.id,
        state="Maharashtra",
        category="new_launches",
        subject_key="bayer soybean three-way mix herbicide",
        claim="Possibly a different Bayer soybean herbicide launch.",
        structured_data={},
        confidence=Decimal("0.60"),
        source_message_ids=["message-2"],
    )
    db_session.add(first)
    db_session.flush()
    upsert_signal(db_session, first)
    db_session.add(second)
    db_session.flush()
    unmatched = upsert_signal(db_session, second, semantic_matcher=FakeSemanticMatcher(confidence=0.84))
    db_session.commit()

    assert unmatched.strength == SignalStrength.WEAK
    assert db_session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "signal.semantic_match")) == 1
    audit = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "signal.semantic_match"))
    assert audit is not None
    assert audit.metadata_json["accepted"] is False


def test_reconciliation_merges_existing_semantic_duplicates_without_losing_evidence(db_session: Session) -> None:
    company, _, employee_one = seed_company(db_session, name="Reconciliation Pilot", phone_number_id="reconcile-channel")
    employee_two = Employee(
        company_id=company.id,
        employee_code="EMP-002",
        employment_type=EmploymentType.CONTRACTUAL,
        state="Maharashtra",
        whatsapp_number="919876543211",
    )
    db_session.add(employee_two)
    db_session.flush()
    first_conversation = FieldConversation(
        company_id=company.id,
        employee_id=employee_one.id,
        started_at=BASE_TIME,
        last_message_at=BASE_TIME,
        employee_context={"state": "Maharashtra"},
    )
    second_conversation = FieldConversation(
        company_id=company.id,
        employee_id=employee_two.id,
        started_at=BASE_TIME,
        last_message_at=BASE_TIME,
        employee_context={"state": "Maharashtra"},
    )
    db_session.add_all([first_conversation, second_conversation])
    db_session.flush()
    observations = [
        Observation(
            company_id=company.id,
            employee_id=employee_one.id,
            conversation_id=first_conversation.id,
            state="Maharashtra",
            category="new_launches",
            subject_key="bayer soybean 3-way mix herbicide",
            claim="Bayer soybean three-way herbicide launch in Ahilyanagar.",
            structured_data={},
            confidence=Decimal("0.90"),
            source_message_ids=["message-1"],
        ),
        Observation(
            company_id=company.id,
            employee_id=employee_two.id,
            conversation_id=second_conversation.id,
            state="Maharashtra",
            category="new_launches",
            subject_key="bayer soybean three-way mix herbicide",
            claim="New Bayer soybean 3-way-mix herbicide in Ahilyanagar.",
            structured_data={},
            confidence=Decimal("0.90"),
            source_message_ids=["message-2"],
        ),
    ]
    db_session.add_all(observations)
    db_session.flush()
    upsert_signal(db_session, observations[0])
    duplicate_signal = upsert_signal(db_session, observations[1])
    assert db_session.scalar(select(func.count()).select_from(Signal)) == 2
    product = Product(
        company_id=company.id,
        ownership=ProductOwnership.COMPETITOR,
        brand="Bayer 3-way mix",
        category="herbicide",
    )
    db_session.add(product)
    db_session.flush()
    historical_price = CompetitionPrice(
        company_id=company.id,
        product_id=product.id,
        state="Maharashtra",
        pack_size="per acre",
        price_type=PriceType.FARMER,
        amount=Decimal("950.00"),
        currency="INR",
        observed_at=BASE_TIME,
        source="strong_field_signal",
        signal_id=duplicate_signal.id,
        evidence_ids=[observations[1].id],
    )
    db_session.add(historical_price)

    merged = reconcile_semantic_duplicates(db_session, company.id, FakeSemanticMatcher(confidence=0.95))
    db_session.commit()

    assert merged == 1
    reconciled = db_session.scalar(select(Signal).where(Signal.company_id == company.id))
    assert reconciled is not None
    assert reconciled.strength == SignalStrength.STRONG
    assert reconciled.distinct_employee_count == 2
    retained_price = db_session.get(CompetitionPrice, historical_price.id)
    assert retained_price is not None
    assert retained_price.signal_id == reconciled.id
    assert db_session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "signal.semantic_merged")) == 1


def test_weekly_intelligence_is_evidence_backed_and_cached_by_fingerprint(db_session: Session) -> None:
    company, _, employee = seed_company(db_session, name="Weekly Pilot", phone_number_id="weekly-channel")
    conversation = FieldConversation(
        company_id=company.id,
        employee_id=employee.id,
        started_at=datetime.now(timezone.utc),
        last_message_at=datetime.now(timezone.utc),
        employee_context={"state": "Maharashtra"},
    )
    db_session.add(conversation)
    db_session.flush()
    observation = Observation(
        company_id=company.id,
        employee_id=employee.id,
        conversation_id=conversation.id,
        state="Maharashtra",
        category="new_launches",
        business_scope=BusinessScope.COMPETITOR,
        subject_key="bayer soybean 3-way herbicide",
        claim="Bayer launched a soybean 3-way herbicide in Maharashtra.",
        structured_data={"mentioned_crops": ["soybean"]},
        confidence=Decimal("0.92"),
        source_message_ids=["weekly-message"],
        created_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )
    db_session.add(observation)
    db_session.flush()
    signal = upsert_signal(db_session, observation)
    historical_observation = Observation(
        company_id=company.id,
        employee_id=employee.id,
        conversation_id=conversation.id,
        state="Maharashtra",
        category="new_launches",
        business_scope=BusinessScope.COMPETITOR,
        subject_key="bayer soybean 3-way herbicide",
        claim="Historical claim outside the selected seven-day window.",
        structured_data={},
        confidence=Decimal("0.80"),
        source_message_ids=["historical-message"],
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    db_session.add(historical_observation)
    db_session.flush()
    db_session.add(
        SignalEvidence(
            company_id=company.id,
            signal_id=signal.id,
            observation_id=historical_observation.id,
            employee_id=employee.id,
            conversation_id=conversation.id,
        )
    )
    db_session.flush()

    class FakeWeeklyClient:
        calls = 0
        supplied_signals: list[dict[str, object]] = []

        def synthesize_weekly_intelligence(self, **kwargs: object):
            self.calls += 1
            self.supplied_signals = list(kwargs["signal_payload"])
            return SimpleNamespace(
                synthesis=WeeklyIntelligenceSynthesis(
                    summary="Bayer's soybean herbicide launch was the week's principal competitive signal.",
                    opportunities=[
                        {
                            "title": "Prepare a channel response",
                            "detail": "Use the launch evidence to brief the Maharashtra sales team.",
                            "business_scope": "competitor",
                            "signal_ids": [signal.id],
                        }
                    ],
                    threats=[],
                    word_cloud=[{"term": "soybean", "weight": 90}, {"term": "Bayer", "weight": 75}],
                    source_signal_ids=[signal.id],
                ),
                profile=SimpleNamespace(provider="openai", model="test-weekly-model"),
                input_tokens=100,
                output_tokens=50,
                latency_ms=20,
            )

    intelligence = FakeWeeklyClient()
    first = get_weekly_intelligence(
        db_session,
        company,
        intelligence,
        week_ending=date(2026, 8, 30),
        state="Maharashtra",
        business_scope="competitor",
    )
    second = get_weekly_intelligence(
        db_session,
        company,
        intelligence,
        week_ending=date(2026, 8, 30),
        state="Maharashtra",
        business_scope="competitor",
    )
    later_observation = Observation(
        company_id=company.id,
        employee_id=employee.id,
        conversation_id=conversation.id,
        state="Maharashtra",
        category="new_launches",
        business_scope=BusinessScope.COMPETITOR,
        subject_key="bayer soybean 3-way herbicide",
        claim="A later update outside the historical week.",
        structured_data={},
        confidence=Decimal("0.90"),
        source_message_ids=["later-message"],
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    db_session.add(later_observation)
    db_session.flush()
    db_session.add(
        SignalEvidence(
            company_id=company.id,
            signal_id=signal.id,
            observation_id=later_observation.id,
            employee_id=employee.id,
            conversation_id=conversation.id,
        )
    )
    signal.last_seen_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    db_session.flush()
    historical_after_update = get_weekly_intelligence(
        db_session,
        company,
        intelligence,
        week_ending=date(2026, 8, 30),
        state="Maharashtra",
        business_scope="competitor",
    )

    assert first["cached"] is False
    assert second["cached"] is True
    assert intelligence.calls == 1
    assert historical_after_update["cached"] is True
    assert historical_after_update["signal_count"] == 1
    assert first["summary"].startswith("Bayer's soybean")
    assert first["opportunities"][0]["signal_ids"] == [signal.id]
    assert first["evidence"][0]["evidence"][0]["employee_code"] == employee.employee_code
    assert "Historical claim" not in json.dumps(intelligence.supplied_signals)
    assert "Historical claim" not in json.dumps(first["evidence"])
    assert db_session.scalar(select(func.count()).select_from(WeeklyBrief)) == 1
