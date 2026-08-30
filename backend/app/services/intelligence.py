"""Evidence-to-observation processing with complete model provenance."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.model_router import QualityTier
from app.ai.openai_client import OpenAIIntelligenceClient
from app.models import AiOperation, FieldConversation, FieldMessage, Observation, Product
from app.services.signals import upsert_signal


def _conversation_evidence(messages: list[FieldMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        visible = message.text_content or message.derived_text or "[media awaiting safe extraction]"
        lines.append(f"MESSAGE {message.id} ({message.message_type.value}): {visible}")
    return "\n".join(lines)


def process_closed_conversation(
    session: Session,
    conversation: FieldConversation,
    client: OpenAIIntelligenceClient,
    tier: QualityTier = QualityTier.AUTO,
) -> int:
    messages = list(
        session.scalars(
            select(FieldMessage)
            .where(FieldMessage.conversation_id == conversation.id)
            .order_by(FieldMessage.provider_timestamp)
        )
    )
    if not messages:
        conversation.analysis_status = "empty"
        return 0
    if any(message.provider_media_id and not message.derived_text for message in messages):
        # Media is never sent to AI before download and malware scanning. Text
        # conversations can already exercise the complete pilot path.
        conversation.analysis_status = "awaiting_media"
        return 0

    try:
        run = client.extract_conversation(
            evidence_text=_conversation_evidence(messages),
            default_state=str(conversation.employee_context["state"]),
            tier=tier,
        )
    except Exception as exc:
        conversation.analysis_status = "manual_review"
        conversation.analysis_error_code = type(exc).__name__
        return 0

    operation = AiOperation(
        company_id=conversation.company_id,
        task_type="conversation_extraction",
        quality_tier=tier.value,
        provider=run.profile.provider,
        model=run.profile.model,
        prompt_version="field-extraction-v1",
        schema_version="conversation-extraction-v1",
        status="succeeded_upgraded" if run.upgraded else "succeeded",
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        latency_ms=run.latency_ms,
    )
    session.add(operation)

    created = 0
    for extracted in run.extraction.observations:
        data = extracted.model_dump(mode="json")
        price = data.get("price")
        if price and price.get("product_id"):
            product = session.scalar(
                select(Product).where(
                    Product.id == price["product_id"], Product.company_id == conversation.company_id
                )
            )
            if not product:
                price["product_id"] = None
        observation = Observation(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            employee_id=conversation.employee_id,
            state=extracted.state or str(conversation.employee_context["state"]),
            category=extracted.category,
            subject_key=extracted.subject_key.casefold().strip(),
            claim=extracted.factual_claim,
            structured_data=data,
            confidence=Decimal(str(extracted.confidence)),
            source_message_ids=[message.id for message in messages],
        )
        session.add(observation)
        session.flush()
        upsert_signal(session, observation, semantic_matcher=client)
        created += 1
    conversation.analysis_status = "processed"
    conversation.analysis_error_code = None
    return created
