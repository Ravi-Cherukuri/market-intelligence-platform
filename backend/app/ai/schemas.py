"""Strict output contracts for untrusted field content."""

from typing import Literal

from pydantic import BaseModel, Field


class PriceObservation(BaseModel):
    product_id: str | None = None
    original_product_text: str
    pack_size: str | None = None
    price_type: Literal["farmer_price", "channel_net_landing"] | None = None
    # JSON Schema encodes constrained Decimal values as a regex that uses
    # lookaround. OpenAI Structured Outputs rejects lookaround expressions, so
    # accept a JSON number here and convert it to Decimal at the persistence
    # boundary where exact currency arithmetic belongs.
    amount: float | None = Field(
        default=None,
        gt=0,
        le=999_999_999_999.99,
        multiple_of=0.01,
        allow_inf_nan=False,
    )
    currency: str = "INR"


class ExtractedObservation(BaseModel):
    business_scope: Literal["own_business", "competitor"]
    category: Literal[
        "pricing_schemes",
        "availability_inventory",
        "competitor_demand",
        "new_launches",
        "product_feedback",
        "pest_disease_incidence",
        "counterfeit_unauthorized",
        "channel_credit",
        "regulatory_label",
        "own_execution",
        "product_acceptance",
        "demand_movement",
        "customer_complaints",
        "competitor_initiatives",
        "new_services",
        "staffing_changes",
    ]
    state: str
    subject_key: str = Field(min_length=3, max_length=300)
    factual_claim: str = Field(min_length=3)
    confidence: float = Field(ge=0, le=1)
    price: PriceObservation | None = None
    mentioned_products: list[str] = []
    mentioned_crops: list[str] = []
    mentioned_pests_or_diseases: list[str] = []


class ConversationExtraction(BaseModel):
    observations: list[ExtractedObservation]
    language: str
    warnings: list[str] = []


class SignalMatchDecision(BaseModel):
    """A constrained semantic-match decision for one incoming observation.

    The model chooses from application-supplied candidate IDs only. The service
    validates the ID again before it can affect a derived signal projection.
    """

    candidate_signal_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    canonical_subject_key: str = Field(min_length=3, max_length=300)
    rationale: str = Field(min_length=3, max_length=400)


class WeeklyInsight(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    detail: str = Field(min_length=3, max_length=360)
    business_scope: Literal["own_business", "competitor"]
    signal_ids: list[str]


class WordCloudTerm(BaseModel):
    term: str = Field(min_length=2, max_length=50)
    weight: int = Field(ge=1, le=100)


class WeeklyIntelligenceSynthesis(BaseModel):
    summary: str = Field(min_length=3, max_length=900)
    opportunities: list[WeeklyInsight]
    threats: list[WeeklyInsight]
    word_cloud: list[WordCloudTerm]
    source_signal_ids: list[str]


class ImageEvidence(BaseModel):
    description: str
    visible_text: str = ""
    warnings: list[str] = []
