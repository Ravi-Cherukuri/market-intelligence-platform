"""Aggregate normalized observations into evidence-backed signals."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.signals import EvidenceIdentity, classify_strength
from app.models import (
    AiOperation,
    AuditEvent,
    CompetitionPrice,
    Observation,
    PriceType,
    Signal,
    SignalEvidence,
    SignalStrength,
)


SEMANTIC_MATCH_CONFIDENCE = 0.85
MAX_SEMANTIC_MATCH_CANDIDATES = 20
_NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}
_ANCHOR_STOP_WORDS = {
    "about", "acre", "and", "around", "dealer", "herbicide", "in", "is", "launch", "new",
    "of", "per", "price", "priced", "report", "the", "to", "way",
}


class SignalMatcher(Protocol):
    def match_signal(self, *, proposed: dict[str, object], candidates: list[dict[str, object]]): ...


def _utc(value: datetime) -> datetime:
    """Normalise SQLite's timezone-naive datetime round trips for comparison."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _identity_anchors(value: str) -> set[str]:
    """Extract stable lexical anchors before asking the probabilistic matcher."""
    tokens = re.findall(r"[a-z0-9]+", value.casefold().replace("-", " "))
    anchors: set[str] = set()
    for token in tokens:
        normalized = _NUMBER_WORDS.get(token, token)
        if normalized in _ANCHOR_STOP_WORDS:
            continue
        # Retain normalized numerals such as 3 in "3-way" / "three-way";
        # other short tokens are too weak to be identity anchors.
        if len(normalized) >= 3 or normalized.isdigit():
            anchors.add(normalized)
    return anchors


def _has_identity_anchor_overlap(proposed: dict[str, object], candidate: Signal) -> bool:
    proposed_text = " ".join(
        str(proposed.get(name, "")) for name in ("subject_key", "claim", "structured_data")
    )
    candidate_text = " ".join((candidate.subject_key, candidate.title, candidate.summary))
    # At least two meaningful anchors makes a confident model decision safer:
    # e.g. Bayer + soybean, not merely two messages mentioning "herbicide".
    return len(_identity_anchors(proposed_text) & _identity_anchors(candidate_text)) >= 2


def upsert_signal(
    session: Session,
    observation: Observation,
    *,
    semantic_matcher: SignalMatcher | None = None,
) -> Signal:
    signal = session.scalar(
        select(Signal).where(
            Signal.company_id == observation.company_id,
            Signal.state == observation.state,
            Signal.category == observation.category,
            Signal.subject_key == observation.subject_key,
        )
    )
    now = datetime.now(timezone.utc)
    if signal is None and semantic_matcher is not None:
        signal = _find_semantic_match(session, observation, semantic_matcher, now)
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


def _find_semantic_match(
    session: Session,
    observation: Observation,
    matcher: SignalMatcher,
    now: datetime,
) -> Signal | None:
    """Ask AI to adjudicate a bounded candidate set after exact lookup misses.

    This is deliberately a high-confidence, same-state/category decision. It
    gives us probabilistic language understanding without allowing a vague
    topical similarity to silently combine distinct market events.
    """
    candidates = list(
        session.scalars(
            select(Signal)
            .where(
                Signal.company_id == observation.company_id,
                Signal.state == observation.state,
                Signal.category == observation.category,
                Signal.last_seen_at >= now - timedelta(days=30),
            )
            .order_by(Signal.last_seen_at.desc())
        )
    )
    proposed = {
        "state": observation.state,
        "category": observation.category,
        "subject_key": observation.subject_key,
        "claim": observation.claim,
        "structured_data": observation.structured_data,
    }
    candidates = [candidate for candidate in candidates if _has_identity_anchor_overlap(proposed, candidate)]
    candidates = candidates[:MAX_SEMANTIC_MATCH_CANDIDATES]
    if not candidates:
        return None
    candidate_payload = [
        {
            "id": candidate.id,
            "subject_key": candidate.subject_key,
            "title": candidate.title,
            "summary": candidate.summary,
            "first_seen_at": candidate.first_seen_at.isoformat(),
            "last_seen_at": candidate.last_seen_at.isoformat(),
        }
        for candidate in candidates
    ]
    try:
        run = matcher.match_signal(proposed=proposed, candidates=candidate_payload)
    except Exception as exc:
        session.add(
            AuditEvent(
                company_id=observation.company_id,
                event_type="signal.semantic_match_failed",
                actor_type="system",
                actor_reference=None,
                metadata_json={"observation_id": observation.id, "error_code": type(exc).__name__},
            )
        )
        # Intelligence enrichment must never block ingestion. Exact matching
        # remains available if the model provider is unavailable.
        return None

    session.add(
        AiOperation(
            company_id=observation.company_id,
            task_type="signal_semantic_match",
            quality_tier="auto",
            provider=run.profile.provider,
            model=run.profile.model,
            prompt_version="signal-match-v1",
            schema_version="signal-match-v1",
            status="succeeded",
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            latency_ms=run.latency_ms,
        )
    )
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    selected = candidate_by_id.get(run.decision.candidate_signal_id or "")
    accepted = selected is not None and run.decision.confidence >= SEMANTIC_MATCH_CONFIDENCE
    session.add(
        AuditEvent(
            company_id=observation.company_id,
            event_type="signal.semantic_match",
            actor_type="system",
            actor_reference=None,
            metadata_json={
                "observation_id": observation.id,
                "original_subject_key": observation.subject_key,
                "candidate_signal_id": run.decision.candidate_signal_id,
                "accepted": accepted,
                "confidence": run.decision.confidence,
                "rationale": run.decision.rationale,
                "canonical_subject_key": run.decision.canonical_subject_key,
            },
        )
    )
    return selected if accepted else None


def reconcile_semantic_duplicates(session: Session, company_id: str, matcher: SignalMatcher) -> int:
    """Merge high-confidence duplicate derived signals without losing evidence.

    Raw messages and observations are never altered. Only the replaceable signal
    projection is reconciled, and every accepted merge receives an audit entry.
    An explicit operator invokes this after deploying a new matching policy.
    """
    # SessionLocal deliberately disables autoflush. Reconciliation must see a
    # just-created derived price before it can safely repoint its foreign key.
    session.flush()
    signals = list(
        session.scalars(
            select(Signal)
            .where(Signal.company_id == company_id)
            .order_by(Signal.first_seen_at, Signal.id)
        )
    )
    merged = 0
    for duplicate in signals:
        if session.get(Signal, duplicate.id) is None:
            continue
        proposed = {
            "state": duplicate.state,
            "category": duplicate.category,
            "subject_key": duplicate.subject_key,
            "claim": duplicate.summary,
            "structured_data": {},
        }
        candidates = [
            candidate
            for candidate in signals
            if candidate.id != duplicate.id
            and session.get(Signal, candidate.id) is not None
            and candidate.state == duplicate.state
            and candidate.category == duplicate.category
            and _utc(candidate.first_seen_at) <= _utc(duplicate.first_seen_at)
            and _utc(candidate.last_seen_at) >= _utc(duplicate.first_seen_at) - timedelta(days=30)
            and _has_identity_anchor_overlap(proposed, candidate)
        ]
        candidates.sort(key=lambda candidate: _utc(candidate.last_seen_at), reverse=True)
        candidates = candidates[:MAX_SEMANTIC_MATCH_CANDIDATES]
        if not candidates:
            continue
        try:
            run = matcher.match_signal(
                proposed=proposed,
                candidates=[
                    {
                        "id": candidate.id,
                        "subject_key": candidate.subject_key,
                        "title": candidate.title,
                        "summary": candidate.summary,
                        "first_seen_at": candidate.first_seen_at.isoformat(),
                        "last_seen_at": candidate.last_seen_at.isoformat(),
                    }
                    for candidate in candidates
                ],
            )
        except Exception as exc:
            session.add(
                AuditEvent(
                    company_id=company_id,
                    event_type="signal.semantic_reconciliation_failed",
                    actor_type="system",
                    actor_reference=None,
                    metadata_json={"duplicate_signal_id": duplicate.id, "error_code": type(exc).__name__},
                )
            )
            continue

        session.add(
            AiOperation(
                company_id=company_id,
                task_type="signal_semantic_match",
                quality_tier="auto",
                provider=run.profile.provider,
                model=run.profile.model,
                prompt_version="signal-match-v1",
                schema_version="signal-match-v1",
                status="succeeded_reconciliation",
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                latency_ms=run.latency_ms,
            )
        )
        candidate_by_id = {candidate.id: candidate for candidate in candidates}
        primary = candidate_by_id.get(run.decision.candidate_signal_id or "")
        if primary is None or run.decision.confidence < SEMANTIC_MATCH_CONFIDENCE:
            session.add(
                AuditEvent(
                    company_id=company_id,
                    event_type="signal.semantic_reconciliation_decision",
                    actor_type="system",
                    actor_reference=None,
                    metadata_json={
                        "duplicate_signal_id": duplicate.id,
                        "candidate_signal_id": run.decision.candidate_signal_id,
                        "accepted": False,
                        "confidence": run.decision.confidence,
                        "rationale": run.decision.rationale,
                    },
                )
            )
            continue

        for evidence in session.scalars(select(SignalEvidence).where(SignalEvidence.signal_id == duplicate.id)):
            evidence.signal_id = primary.id
        # CompetitionPrice is an append-only historical projection. Preserve a
        # price already established from the duplicate's evidence and repoint it
        # before deleting that replaceable Signal row (PostgreSQL enforces this
        # foreign key even though SQLite tests may not).
        duplicate_prices = list(
            session.scalars(select(CompetitionPrice).where(CompetitionPrice.signal_id == duplicate.id))
        )
        for price in duplicate_prices:
            price.signal_id = primary.id
        primary.last_seen_at = max(_utc(primary.last_seen_at), _utc(duplicate.last_seen_at))
        session.flush()
        session.delete(duplicate)
        session.flush()
        prior_strength = primary.strength
        _refresh_signal_strength(session, primary, datetime.now(timezone.utc))
        if prior_strength == SignalStrength.WEAK and primary.strength == SignalStrength.STRONG and not duplicate_prices:
            representative = session.scalar(
                select(Observation)
                .join(SignalEvidence, SignalEvidence.observation_id == Observation.id)
                .where(SignalEvidence.signal_id == primary.id)
                .order_by(Observation.created_at.desc())
            )
            if representative:
                _append_price_if_present(session, primary, representative)
        session.add(
            AuditEvent(
                company_id=company_id,
                event_type="signal.semantic_merged",
                actor_type="system",
                actor_reference=None,
                metadata_json={
                    "primary_signal_id": primary.id,
                    "merged_signal_id": duplicate.id,
                    "repointed_price_count": len(duplicate_prices),
                    "confidence": run.decision.confidence,
                    "rationale": run.decision.rationale,
                },
            )
        )
        merged += 1
    return merged


def _refresh_signal_strength(session: Session, signal: Signal, now: datetime) -> None:
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
