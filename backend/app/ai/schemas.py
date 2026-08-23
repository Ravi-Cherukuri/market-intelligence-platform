"""Strict output contracts for untrusted field content."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PriceObservation(BaseModel):
    product_id: str | None = None
    original_product_text: str
    pack_size: str | None = None
    price_type: Literal["farmer_price", "channel_net_landing"] | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str = "INR"


class ExtractedObservation(BaseModel):
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


class ImageEvidence(BaseModel):
    description: str
    visible_text: str = ""
    warnings: list[str] = []
