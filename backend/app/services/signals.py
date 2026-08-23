"""Aggregate normalized observations into evidence-backed signals."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.signals import EvidenceIdentity, classify_strength
from app.models import (
    CompetitionPrice,
    Observation,
    PriceType,
    Signal,
    SignalEvidence,
    SignalStrength,
)


def upsert_signal(session: Session, observation: Observation) -> Signal:
    signal = session.scalar(
        select(Signal).where(
            Signal.company_id == observation.company_id,
            Signal.state == observation.state,
            Signal.category == observation.category,
            Signal.subject_key == observation.subject_key,
        )
    )
    now = datetime.now(timezone.utc)
    if signal is None:
        signal = Signal(
            company_id=observation.company_id,
            state=observation.state,
            category=observation.category,
            subject_key=observation.subject_key,
            title=observation.claim[:300],
            summary=observation.claim,
            strength=SignalStrength.WEAK,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(signal)
        session.flush()

    prior_strength = signal.strength
    existing = session.scalar(
        select(SignalEvidence.id).where(
            SignalEvidence.signal_id == signal.id,
            SignalEvidence.observation_id == observation.id,
        )
    )
    if not existing:
        session.add(
            SignalEvidence(
                company_id=observation.company_id,
                signal_id=signal.id,
                observation_id=observation.id,
                employee_id=observation.employee_id,
                conversation_id=observation.conversation_id,
            )
        )
        session.flush()

    evidence_window_start = now - timedelta(days=30)
    evidence = session.execute(
        select(SignalEvidence.employee_id, SignalEvidence.conversation_id)
        .join(Observation, Observation.id == SignalEvidence.observation_id)
        .where(SignalEvidence.signal_id == signal.id, Observation.created_at >= evidence_window_start)
    ).all()
    strength, employee_count, conversation_count = classify_strength(
        EvidenceIdentity(employee_id=row.employee_id, conversation_id=row.conversation_id) for row in evidence
    )
    signal.strength = SignalStrength(strength)
    signal.distinct_employee_count = employee_count
    signal.distinct_conversation_count = conversation_count
    signal.last_seen_at = now

    if prior_strength == SignalStrength.WEAK and signal.strength == SignalStrength.STRONG:
        _append_price_if_present(session, signal, observation)
    return signal


def _append_price_if_present(session: Session, signal: Signal, observation: Observation) -> None:
    rows = session.execute(
        select(Observation, SignalEvidence.employee_id)
        .join(SignalEvidence, SignalEvidence.observation_id == Observation.id)
        .where(
            SignalEvidence.signal_id == signal.id,
            Observation.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
        )
    ).all()
    grouped: dict[tuple[str, str, str, str, str], set[str]] = defaultdict(set)
    evidence_for_fingerprint: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    prices: dict[tuple[str, str, str, str, str], dict] = {}
    for evidence_observation, employee_id in rows:
        price = evidence_observation.structured_data.get("price") if evidence_observation.structured_data else None
        if not price or not price.get("product_id") or not price.get("amount") or not price.get("price_type"):
            continue
        fingerprint = (
            str(price["product_id"]),
            str(price.get("pack_size") or "unspecified").casefold(),
            str(price["price_type"]),
            str(Decimal(str(price["amount"])).quantize(Decimal("0.01"))),
            str(price.get("currency", "INR")).upper(),
        )
        grouped[fingerprint].add(employee_id)
        evidence_for_fingerprint[fingerprint].append(evidence_observation.id)
        prices[fingerprint] = price

    corroborated = next((fingerprint for fingerprint, employees in grouped.items() if len(employees) >= 2), None)
    if corroborated is None:
        # Conflicting prices stay visible as evidence but do not update the
        # current-price projection until independently corroborated.
        return
    price = prices[corroborated]
    session.add(
        CompetitionPrice(
            company_id=signal.company_id,
            product_id=price["product_id"],
            state=signal.state,
            pack_size=price.get("pack_size") or "unspecified",
            price_type=PriceType(price["price_type"]),
            amount=Decimal(str(price["amount"])),
            currency=price.get("currency", "INR"),
            observed_at=signal.last_seen_at,
            source="strong_field_signal",
            signal_id=signal.id,
            evidence_ids=evidence_for_fingerprint[corroborated],
        )
    )
