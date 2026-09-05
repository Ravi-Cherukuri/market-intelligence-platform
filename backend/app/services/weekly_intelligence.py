"""Build and cache the deliberately small weekly dashboard brief."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.ai.openai_client import OpenAIIntelligenceClient
from app.domain.signals import EvidenceIdentity, classify_strength
from app.models import (
    AiOperation,
    BusinessScope,
    Company,
    Employee,
    Observation,
    Signal,
    SignalEvidence,
    WeeklyBrief,
)

INDIA = ZoneInfo("Asia/Kolkata")
VALID_SCOPES = {"all", BusinessScope.OWN_BUSINESS.value, BusinessScope.COMPETITOR.value}
WEEKLY_SYNTHESIS_VERSION = "weekly-dashboard-v1"
MAX_WEEKLY_SIGNALS = 50
MAX_EVIDENCE_PER_SIGNAL = 8


def period_for_week_ending(week_ending: date) -> tuple[datetime, datetime]:
    end_local = datetime.combine(week_ending + timedelta(days=1), time.min, tzinfo=INDIA)
    start_local = end_local - timedelta(days=7)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def available_states(session: Session, company_id: str) -> list[str]:
    return list(
        session.scalars(
            select(Employee.state)
            .where(Employee.company_id == company_id, Employee.active.is_(True))
            .distinct()
            .order_by(Employee.state)
        )
    )


def _signal_payload(
    session: Session,
    company_id: str,
    period_start: datetime,
    period_end: datetime,
    state: str | None,
    business_scope: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    # Derived Signal timestamps are mutable. Select through immutable evidence
    # so asking for a historical week remains stable after later reports arrive.
    query = (
        select(Signal)
        .join(SignalEvidence, SignalEvidence.signal_id == Signal.id)
        .join(Observation, Observation.id == SignalEvidence.observation_id)
        .where(
            Signal.company_id == company_id,
            Observation.created_at >= period_start,
            Observation.created_at < period_end,
        )
    )
    if state:
        query = query.where(Signal.state == state)
    signals = list(
        session.scalars(
            query.group_by(Signal.id)
            .order_by(
                func.count(func.distinct(Observation.employee_id)).desc(),
                func.max(Observation.created_at).desc(),
            )
            .limit(MAX_WEEKLY_SIGNALS)
        ).unique()
    )
    synthesis_payload: list[dict[str, object]] = []
    evidence_payload: list[dict[str, object]] = []
    for signal in signals:
        rows = session.execute(
            select(Observation, Employee.employee_code)
            .join(SignalEvidence, SignalEvidence.observation_id == Observation.id)
            .join(Employee, Employee.id == Observation.employee_id)
            .where(
                SignalEvidence.signal_id == signal.id,
                Observation.created_at >= period_start,
                Observation.created_at < period_end,
            )
            .order_by(Observation.created_at.desc())
            .limit(MAX_EVIDENCE_PER_SIGNAL)
        ).all()
        if not rows:
            continue
        scopes = {observation.business_scope.value for observation, _ in rows}
        signal_scope = (
            BusinessScope.OWN_BUSINESS.value
            if scopes == {BusinessScope.OWN_BUSINESS.value}
            else BusinessScope.COMPETITOR.value
        )
        if business_scope != "all" and signal_scope != business_scope:
            continue
        evidence = [
            {
                "observation_id": observation.id,
                "employee_code": employee_code,
                "claim": observation.claim,
                "confidence": float(observation.confidence),
                "observed_at": observation.created_at.isoformat(),
            }
            for observation, employee_code in rows
        ]
        strength, employee_count, _ = classify_strength(
            EvidenceIdentity(employee_id=observation.employee_id, conversation_id=observation.conversation_id)
            for observation, _ in rows
        )
        latest_observation = rows[0][0]
        item = {
            "id": signal.id,
            "title": latest_observation.claim[:300],
            "summary": latest_observation.claim,
            "state": signal.state,
            "category": signal.category,
            "business_scope": signal_scope,
            "strength": strength,
            "distinct_employee_count": employee_count,
            "last_seen_at": latest_observation.created_at.isoformat(),
            "claims": [entry["claim"] for entry in evidence],
        }
        synthesis_payload.append(item)
        evidence_payload.append({**item, "evidence": evidence})
    return synthesis_payload, evidence_payload


def _empty_synthesis() -> dict[str, object]:
    return {
        "summary": "No field intelligence was received for this selection during the last seven days.",
        "opportunities": [],
        "threats": [],
        "word_cloud": [],
        "source_signal_ids": [],
    }


def _validated_content(raw: dict[str, object], signal_scopes: dict[str, str]) -> dict[str, object]:
    def insights(name: str) -> list[dict[str, object]]:
        accepted: list[dict[str, object]] = []
        for item in list(raw.get(name, []))[:3]:
            if not isinstance(item, dict):
                continue
            declared_scope = item.get("business_scope")
            ids = [
                value
                for value in item.get("signal_ids", [])
                if value in signal_scopes and signal_scopes[value] == declared_scope
            ]
            if ids:
                accepted.append({**item, "signal_ids": ids})
        return accepted

    return {
        "summary": str(raw.get("summary", "")),
        "opportunities": insights("opportunities"),
        "threats": insights("threats"),
        "word_cloud": _deduplicated_word_cloud(list(raw.get("word_cloud", []))),
        "source_signal_ids": [value for value in raw.get("source_signal_ids", []) if value in signal_scopes],
    }


def _deduplicated_word_cloud(items: list[object]) -> list[dict[str, object]]:
    accepted: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("term", "")).casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        accepted.append(item)
        if len(accepted) == 24:
            break
    return accepted


def get_weekly_intelligence(
    session: Session,
    company: Company,
    client: OpenAIIntelligenceClient,
    *,
    week_ending: date,
    state: str | None,
    business_scope: str,
) -> dict[str, object]:
    if business_scope not in VALID_SCOPES:
        raise ValueError("Unknown business scope")
    period_start, period_end = period_for_week_ending(week_ending)
    signal_payload, evidence_payload = _signal_payload(
        session, company.id, period_start, period_end, state, business_scope
    )
    encoded = json.dumps(
        {"synthesis_version": WEEKLY_SYNTHESIS_VERSION, "signals": signal_payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    # The production API can receive rapid duplicate requests (for example an
    # aborted browser fetch followed by a reload). One transaction performs the
    # paid synthesis; peers wait and then reuse its committed cache row.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        advisory_key = int(fingerprint[:16], 16)
        if advisory_key >= 2**63:
            advisory_key -= 2**64
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": advisory_key})
    state_scope = state or "__country__"
    cached = session.scalar(
        select(WeeklyBrief).where(
            WeeklyBrief.company_id == company.id,
            WeeklyBrief.state_scope == state_scope,
            WeeklyBrief.business_scope == business_scope,
            WeeklyBrief.period_end == period_end,
            WeeklyBrief.source_fingerprint == fingerprint,
        )
    )
    if cached:
        content = cached.content_json
        generated_at = cached.created_at
        cached_result = True
    elif not signal_payload:
        content = _empty_synthesis()
        generated_at = datetime.now(timezone.utc)
        cached_result = False
    else:
        run = client.synthesize_weekly_intelligence(
            signal_payload=signal_payload,
            geography_label=state or "India",
            scope_label=business_scope,
        )
        content = _validated_content(
            run.synthesis.model_dump(mode="json"),
            {str(item["id"]): str(item["business_scope"]) for item in signal_payload},
        )
        brief = WeeklyBrief(
            company_id=company.id,
            state_scope=state_scope,
            business_scope=business_scope,
            period_start=period_start,
            period_end=period_end,
            source_fingerprint=fingerprint,
            content_json=content,
            provider=run.profile.provider,
            model=run.profile.model,
        )
        session.add(brief)
        session.add(
            AiOperation(
                company_id=company.id,
                task_type="weekly_intelligence_synthesis",
                quality_tier="economy",
                provider=run.profile.provider,
                model=run.profile.model,
                prompt_version=WEEKLY_SYNTHESIS_VERSION,
                schema_version="weekly-intelligence-v1",
                status="succeeded",
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                latency_ms=run.latency_ms,
            )
        )
        session.flush()
        generated_at = brief.created_at
        cached_result = False

    return {
        **content,
        "company_name": company.name,
        "geography": state or "India",
        "state": state,
        "business_scope": business_scope,
        "week_ending": week_ending.isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "generated_at": generated_at.isoformat(),
        "cached": cached_result,
        "available_states": available_states(session, company.id),
        "signal_count": len(signal_payload),
        "evidence": evidence_payload,
    }
