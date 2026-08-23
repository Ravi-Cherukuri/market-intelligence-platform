"""Cost-aware, quality-gated model routing.

Model names are configuration, not business logic. The default registry is a
safe starting point for the pilot and can be replaced without changing prompts,
schemas or evidence records.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class QualityTier(StrEnum):
    AUTO = "auto"
    ECONOMY = "economy"
    BALANCED = "balanced"
    PREMIUM = "premium"


class TaskType(StrEnum):
    EXTRACTION = "extraction"
    IMAGE_INTERPRETATION = "image_interpretation"
    TRANSCRIPTION = "transcription"
    SIGNAL_MATCHING = "signal_matching"
    REPORT_SYNTHESIS = "report_synthesis"
    CONVERSATIONAL_ANALYSIS = "conversational_analysis"


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str
    tasks: frozenset[TaskType]
    quality_score: int
    cost_rank: int


DEFAULT_PROFILES = (
    ModelProfile(
        provider="openai",
        model="gpt-5.6-terra",
        tasks=frozenset(
            {
                TaskType.EXTRACTION,
                TaskType.IMAGE_INTERPRETATION,
                TaskType.SIGNAL_MATCHING,
                TaskType.REPORT_SYNTHESIS,
                TaskType.CONVERSATIONAL_ANALYSIS,
            }
        ),
        quality_score=75,
        cost_rank=1,
    ),
    ModelProfile(
        provider="openai",
        model="gpt-5.6",
        tasks=frozenset(
            {
                TaskType.EXTRACTION,
                TaskType.IMAGE_INTERPRETATION,
                TaskType.SIGNAL_MATCHING,
                TaskType.REPORT_SYNTHESIS,
                TaskType.CONVERSATIONAL_ANALYSIS,
            }
        ),
        quality_score=95,
        cost_rank=3,
    ),
    ModelProfile(
        provider="openai",
        model="gpt-4o-mini-transcribe",
        tasks=frozenset({TaskType.TRANSCRIPTION}),
        quality_score=80,
        cost_rank=1,
    ),
)


TASK_QUALITY_TARGETS = {
    TaskType.EXTRACTION: 72,
    TaskType.IMAGE_INTERPRETATION: 75,
    TaskType.TRANSCRIPTION: 75,
    TaskType.SIGNAL_MATCHING: 75,
    TaskType.REPORT_SYNTHESIS: 85,
    TaskType.CONVERSATIONAL_ANALYSIS: 85,
}


class NoEligibleModel(RuntimeError):
    pass


class ModelRouter:
    def __init__(self, profiles: tuple[ModelProfile, ...] = DEFAULT_PROFILES):
        self.profiles = profiles

    def route(self, task: TaskType, tier: QualityTier = QualityTier.AUTO) -> ModelProfile:
        candidates = [profile for profile in self.profiles if task in profile.tasks]
        if not candidates:
            raise NoEligibleModel(f"No model supports {task}")

        if tier == QualityTier.PREMIUM:
            return max(candidates, key=lambda item: (item.quality_score, -item.cost_rank))
        if tier == QualityTier.BALANCED:
            target = max(80, TASK_QUALITY_TARGETS[task])
        elif tier == QualityTier.ECONOMY:
            target = 0
        else:
            target = TASK_QUALITY_TARGETS[task]

        eligible = [candidate for candidate in candidates if candidate.quality_score >= target]
        if not eligible:
            raise NoEligibleModel(f"No {tier} model meets the quality target for {task}")
        return min(eligible, key=lambda item: (item.cost_rank, -item.quality_score))

    def upgrade(self, current: ModelProfile, task: TaskType) -> ModelProfile | None:
        """Return the next higher-quality approved model after validation failure."""
        candidates = sorted(
            (
                profile
                for profile in self.profiles
                if task in profile.tasks and profile.quality_score > current.quality_score
            ),
            key=lambda item: (item.cost_rank, item.quality_score),
        )
        return candidates[0] if candidates else None
