"""Relational domain model.

Every business record carries ``company_id`` even though the pilot has one
company. This prevents a future multi-company migration from contaminating
evidence, retrieval or reports. Raw field messages and price observations are
append-only; derived projections point back to them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    CONTRACTUAL = "contractual"


class ConversationStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class MessageType(str, enum.Enum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"
    LOCATION = "location"
    UNSUPPORTED = "unsupported"


class ProductOwnership(str, enum.Enum):
    OWN = "own"
    COMPETITOR = "competitor"


class PriceType(str, enum.Enum):
    FARMER = "farmer_price"
    CHANNEL_NET_LANDING = "channel_net_landing"


class SignalStrength(str, enum.Enum):
    WEAK = "weak"
    STRONG = "strong"


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WhatsAppChannel(Base, TimestampMixin):
    __tablename__ = "whatsapp_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    phone_number_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_phone_number: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("company_id", "employee_code", name="uq_employee_code_company"),
        Index(
            "uq_employee_active_whatsapp_company",
            "company_id",
            "whatsapp_number",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    employee_code: Mapped[str] = mapped_column(String(80), nullable=False)
    employment_type: Mapped[EmploymentType] = mapped_column(Enum(EmploymentType, native_enum=False))
    designation: Mapped[str | None] = mapped_column(String(160))
    territory_code: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    whatsapp_number: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SalesOrgNode(Base, TimestampMixin):
    __tablename__ = "sales_org_nodes"
    __table_args__ = (UniqueConstraint("company_id", "code", "effective_from", name="uq_soh_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(30), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("sales_org_nodes.id"))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PoliticalNode(Base, TimestampMixin):
    __tablename__ = "political_nodes"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_political_code_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(30), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("political_nodes.id"))


class SalesPoliticalMapping(Base, TimestampMixin):
    __tablename__ = "sales_political_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    sales_org_node_id: Mapped[str] = mapped_column(ForeignKey("sales_org_nodes.id"), nullable=False)
    subdistrict_id: Mapped[str] = mapped_column(ForeignKey("political_nodes.id"), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FieldConversation(Base, TimestampMixin):
    __tablename__ = "field_conversations"
    __table_args__ = (Index("ix_open_conversation_lookup", "company_id", "employee_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, native_enum=False), default=ConversationStatus.OPEN, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(String(40))
    employee_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    analysis_status: Mapped[str] = mapped_column(String(30), default="waiting", nullable=False)
    analysis_error_code: Mapped[str | None] = mapped_column(String(100))


class FieldMessage(Base, TimestampMixin):
    __tablename__ = "field_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("field_conversations.id"), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    message_type: Mapped[MessageType] = mapped_column(Enum(MessageType, native_enum=False), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    derived_text: Mapped[str | None] = mapped_column(Text)
    provider_media_id: Mapped[str | None] = mapped_column(String(180))
    provider_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)


class InboundMessageReceipt(Base):
    """Content-free provider idempotency record for every inbound message."""

    __tablename__ = "inbound_message_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str | None] = mapped_column(String(36), index=True)
    provider_message_id: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    disposition: Mapped[str] = mapped_column(String(40), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("field_messages.id"), nullable=False)
    provider_media_id: Mapped[str] = mapped_column(String(180), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(600))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    sha256: Mapped[str | None] = mapped_column(String(64))
    scan_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    analysis_status: Mapped[str] = mapped_column(String(30), default="waiting", nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class OutboundMessage(Base, TimestampMixin):
    """Durable outbound queue; API calls are made by a worker, never a webhook."""

    __tablename__ = "outbound_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_channels.id"), nullable=False)
    recipient_wa_id: Mapped[str] = mapped_column(String(20), nullable=False)
    message_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "ownership", "brand", name="uq_product_brand_owner"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    ownership: Mapped[ProductOwnership] = mapped_column(Enum(ProductOwnership, native_enum=False))
    manufacturer: Mapped[str | None] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    active_ingredient: Mapped[str | None] = mapped_column(String(240))
    formulation: Mapped[str | None] = mapped_column(String(160))
    concentration: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProductAlias(Base, TimestampMixin):
    __tablename__ = "product_aliases"
    __table_args__ = (UniqueConstraint("company_id", "normalized_alias", name="uq_product_alias_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(240), nullable=False)


class CompetitionPrice(Base, TimestampMixin):
    __tablename__ = "competition_prices"
    __table_args__ = (
        Index("ix_price_current_lookup", "company_id", "product_id", "state", "pack_size", "price_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    pack_size: Mapped[str] = mapped_column(String(80), nullable=False)
    price_type: Mapped[PriceType] = mapped_column(Enum(PriceType, native_enum=False), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    signal_id: Mapped[str | None] = mapped_column(ForeignKey("signals.id"))
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class Observation(Base, TimestampMixin):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("field_conversations.id"), nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(300), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    structured_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    source_message_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="unreviewed", nullable=False)


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("company_id", "state", "category", "subject_key", name="uq_signal_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[SignalStrength] = mapped_column(Enum(SignalStrength, native_enum=False), nullable=False)
    distinct_employee_count: Mapped[int] = mapped_column(default=1, nullable=False)
    distinct_conversation_count: Mapped[int] = mapped_column(default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SignalEvidence(Base):
    __tablename__ = "signal_evidence"
    __table_args__ = (UniqueConstraint("signal_id", "observation_id", name="uq_signal_observation"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), nullable=False)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"), nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("field_conversations.id"), nullable=False)


class AiOperation(Base, TimestampMixin):
    __tablename__ = "ai_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_tier: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(String(80))


class RetentionPolicy(Base, TimestampMixin):
    __tablename__ = "retention_policies"
    __table_args__ = (UniqueConstraint("company_id", "data_type", name="uq_retention_type_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), nullable=False, index=True)
    data_type: Mapped[str] = mapped_column(String(60), nullable=False)
    retention_days: Mapped[int | None]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str | None] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_reference: Mapped[str | None] = mapped_column(String(180))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
