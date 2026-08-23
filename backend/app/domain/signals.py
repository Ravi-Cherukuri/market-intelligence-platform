"""Evidence corroboration policy."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceIdentity:
    employee_id: str
    conversation_id: str


def classify_strength(evidence: Iterable[EvidenceIdentity]) -> tuple[str, int, int]:
    items = list(evidence)
    employees = {item.employee_id for item in items}
    conversations = {item.conversation_id for item in items}
    strength = "strong" if len(employees) >= 2 else "weak"
    return strength, len(employees), len(conversations)
