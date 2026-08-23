"""Single-monolith background worker.

The API and worker share one codebase and database but run as separate processes
so webhook acknowledgement is independent of network-bound media and AI work.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.domain.conversations import utc_aware
from app.integrations.object_store import S3MediaStore
from app.integrations.malware import ClamAVScanner, MalwareDetected
from app.integrations.whatsapp import WhatsAppClient, WhatsAppConfigurationError
from app.ai.openai_client import OpenAIIntelligenceClient
from app.models import (
    ConversationStatus,
    FieldConversation,
    FieldMessage,
    MediaAsset,
    OutboundMessage,
    WhatsAppChannel,
)
from app.services.intelligence import process_closed_conversation

logger = logging.getLogger("market_intelligence.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def close_inactive_conversations() -> int:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.conversation_timeout_minutes)
    with SessionLocal() as session:
        conversations = list(
            session.scalars(select(FieldConversation).where(FieldConversation.status == ConversationStatus.OPEN))
        )
        changed = 0
        for conversation in conversations:
            if utc_aware(conversation.last_message_at) <= cutoff:
                conversation.status = ConversationStatus.CLOSED
                conversation.closed_at = cutoff
                conversation.close_reason = "inactivity"
                changed += 1
        session.commit()
        return changed


def process_outbound_messages() -> int:
    settings = get_settings()
    try:
        client = WhatsAppClient(
            base_url=settings.whatsapp_graph_base_url,
            api_version=settings.whatsapp_api_version,
            access_token=settings.whatsapp_access_token,
        )
    except WhatsAppConfigurationError:
        return 0
    with SessionLocal() as session:
        jobs = list(
            session.scalars(
                select(OutboundMessage).where(OutboundMessage.status == "pending").order_by(OutboundMessage.created_at).limit(10)
            )
        )
        for job in jobs:
            channel = session.get(WhatsAppChannel, job.channel_id)
            if not channel:
                job.status = "failed"
                job.last_error_code = "channel_missing"
                continue
            try:
                client.send_text(channel.phone_number_id, job.recipient_wa_id, job.body)
                job.status = "sent"
            except Exception as exc:  # provider errors are recorded without response bodies or secrets
                job.attempts += 1
                job.last_error_code = type(exc).__name__
                job.status = "failed" if job.attempts >= 5 else "pending"
        session.commit()
        return len(jobs)


def process_media_assets() -> int:
    settings = get_settings()
    try:
        client = WhatsAppClient(
            base_url=settings.whatsapp_graph_base_url,
            api_version=settings.whatsapp_api_version,
            access_token=settings.whatsapp_access_token,
        )
    except WhatsAppConfigurationError:
        return 0
    store = S3MediaStore(settings.s3_bucket, settings.aws_region)
    # The t4g.small pilot does not run the memory-heavy ClamAV daemon. The
    # scanner remains available for a later larger-instance deployment.
    scanner = (
        ClamAVScanner(settings.clamav_host, settings.clamav_port)
        if settings.clamav_host
        else None
    )
    with SessionLocal() as session:
        assets = list(
            session.scalars(
                select(MediaAsset).where(MediaAsset.scan_status == "pending").order_by(MediaAsset.created_at).limit(5)
            )
        )
        for asset in assets:
            try:
                media = client.download_media(asset.provider_media_id)
                if scanner:
                    scanner.assert_clean(media.content)
                key, digest = store.put_inbound_media(
                    company_id=asset.company_id,
                    media_id=asset.provider_media_id,
                    content=media.content,
                    mime_type=media.mime_type,
                    received_at=asset.created_at,
                )
                asset.object_key = key
                asset.sha256 = digest
                asset.mime_type = media.mime_type
                asset.scan_status = "clean" if scanner else "accepted_unscanned_pilot"
                if settings.openai_api_key:
                    intelligence = OpenAIIntelligenceClient(settings.openai_api_key)
                    message = session.get(FieldMessage, asset.message_id)
                    if message and media.mime_type.startswith("audio/"):
                        message.derived_text = intelligence.transcribe_audio(
                            content=media.content, mime_type=media.mime_type
                        )
                        asset.analysis_status = "processed"
                    elif message and media.mime_type.startswith("image/"):
                        message.derived_text = intelligence.interpret_image(
                            content=media.content, mime_type=media.mime_type
                        )
                        asset.analysis_status = "processed"
                    if message:
                        conversation = session.get(FieldConversation, message.conversation_id)
                        if conversation and conversation.status == ConversationStatus.CLOSED:
                            conversation.analysis_status = "waiting"
            except MalwareDetected:
                asset.scan_status = "rejected_malware"
                asset.analysis_status = "blocked"
            except Exception as exc:
                asset.attempts += 1
                asset.last_error_code = type(exc).__name__
                asset.scan_status = "failed" if asset.attempts >= 5 else "pending"
        session.commit()
        return len(assets)


def process_text_intelligence() -> int:
    settings = get_settings()
    if not settings.openai_api_key:
        return 0
    client = OpenAIIntelligenceClient(settings.openai_api_key)
    with SessionLocal() as session:
        conversations = list(
            session.scalars(
                select(FieldConversation)
                .where(
                    FieldConversation.status == ConversationStatus.CLOSED,
                    FieldConversation.analysis_status == "waiting",
                )
                .order_by(FieldConversation.closed_at)
                .limit(5)
            )
        )
        for conversation in conversations:
            process_closed_conversation(session, conversation, client)
        session.commit()
        return len(conversations)


def run_forever() -> None:
    logger.info("background worker started")
    while True:
        try:
            closed = close_inactive_conversations()
            outbound = process_outbound_messages()
            media = process_media_assets()
            intelligence = process_text_intelligence()
            if closed or outbound or media or intelligence:
                logger.info(
                    "worker cycle closed=%s outbound=%s media=%s intelligence=%s",
                    closed,
                    outbound,
                    media,
                    intelligence,
                )
        except Exception:
            logger.exception("worker cycle failed")
        time.sleep(3)


if __name__ == "__main__":
    run_forever()
