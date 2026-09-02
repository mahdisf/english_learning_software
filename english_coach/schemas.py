"""Strict Pydantic contracts for the canonical AI session-update JSON.

These models are the single source of truth for ``schemas/session_update.schema.json``.
Run ``python -m english_coach.schemas`` (or the ``dev-gen-schema`` helper in
tests) to regenerate the JSON Schema file after changing anything here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

SessionType = Literal[
    "conversation",
    "technical_interview",
    "behavioral_interview",
    "leadership",
    "professional_communication",
    "presentation",
    "academic",
    "other",
]

ExpressionType = Literal[
    "idiom",
    "phrasal_verb",
    "collocation",
    "professional_expression",
    "sentence_chunk",
    "other",
]

Severity = Literal["low", "medium", "high"]
ObservedFrom = Literal["user", "coach", "both"]
EventType = Literal[
    "user_production", "prompted_recall", "coach_introduction", "mistake_occurrence"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionObject(StrictModel):
    session_id: UUID
    started_at: datetime | None = None
    ended_at: datetime
    topic: str = Field(min_length=1)
    session_type: SessionType
    summary: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    fluency_notes: list[str] = Field(default_factory=list)
    next_focus: list[str] = Field(default_factory=list)


class CommonItemFields(StrictModel):
    client_ref: str = Field(min_length=1)
    item_id: UUID | None = None
    importance_score: int = Field(ge=1, le=10)
    cefr_level: Literal["A1", "A2", "B1", "B2", "C1", "C2"] | None = None
    topics: list[str] = Field(default_factory=list)
    source_context: str = Field(min_length=1)
    selection_reason: str = Field(min_length=1)
    observed_from: ObservedFrom


class VocabularyItem(CommonItemFields):
    word: str = Field(min_length=1)
    lemma: str = Field(min_length=1)
    part_of_speech: str = Field(min_length=1)
    sense_key: str = Field(min_length=1)
    meaning_english: str = Field(min_length=1)
    meaning_persian: str | None = None
    ipa_american: str | None = None
    stress_note: str | None = None
    examples: list[str] = Field(default_factory=list)
    collocations: list[str] = Field(default_factory=list)
    usage_note: str | None = None
    common_errors: list[str] = Field(default_factory=list)


class ExpressionItem(CommonItemFields):
    expression: str = Field(min_length=1)
    expression_type: ExpressionType
    meaning_english: str = Field(min_length=1)
    meaning_persian: str | None = None
    ipa_american: str | None = None
    examples: list[str] = Field(default_factory=list)
    usage_contexts: list[str] = Field(default_factory=list)
    common_errors: list[str] = Field(default_factory=list)


class GrammarItem(CommonItemFields):
    pattern_name: str = Field(min_length=1)
    explanation_english: str = Field(min_length=1)
    explanation_persian: str | None = None
    structure: str = Field(min_length=1)
    examples: list[str] = Field(default_factory=list)
    learner_problem: str = Field(min_length=1)
    common_errors: list[str] = Field(default_factory=list)


class MistakeItem(CommonItemFields):
    wrong_sentence: str = Field(min_length=1)
    corrected_sentence: str = Field(min_length=1)
    category: str = Field(min_length=1)
    explanation_english: str = Field(min_length=1)
    explanation_persian: str | None = None
    severity: Severity
    evidence: str = Field(min_length=1)
    additional_examples: list[str] = Field(default_factory=list)
    occurrences_in_session: int = Field(ge=1)


class UsageEvent(StrictModel):
    event_id: UUID
    item_id: UUID | None = None
    client_ref: str | None = None
    event_type: EventType
    correctness: bool | None = None
    evidence_context: str = Field(min_length=1)
    correction: str | None = None
    occurred_at: datetime

    @model_validator(mode="after")
    def _exactly_one_reference(self) -> "UsageEvent":
        has_item_id = self.item_id is not None
        has_client_ref = self.client_ref is not None
        if has_item_id == has_client_ref:
            raise ValueError(
                "usage_events entries must set exactly one of item_id or client_ref"
            )
        return self


class WeakPointUpsert(StrictModel):
    key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Severity
    evidence: list[str] = Field(default_factory=list)
    last_seen_at: datetime


class MemoryPatch(StrictModel):
    current_topics_add: list[str] = Field(default_factory=list)
    current_topics_remove: list[str] = Field(default_factory=list)
    active_goals_add: list[str] = Field(default_factory=list)
    active_goals_remove: list[str] = Field(default_factory=list)
    completed_topics_add: list[str] = Field(default_factory=list)
    weak_points_upsert: list[WeakPointUpsert] = Field(default_factory=list)
    weak_points_resolved: list[str] = Field(default_factory=list)
    next_session_focus: list[str] = Field(default_factory=list)


class SessionUpdate(StrictModel):
    schema_version: Literal["1.0"]
    update_id: UUID
    generated_at: datetime
    language_standard: Literal["en-US"]
    session: SessionObject
    vocabulary: list[VocabularyItem] = Field(default_factory=list)
    expressions: list[ExpressionItem] = Field(default_factory=list)
    grammar_patterns: list[GrammarItem] = Field(default_factory=list)
    mistakes: list[MistakeItem] = Field(default_factory=list)
    usage_events: list[UsageEvent] = Field(default_factory=list)
    memory_patch: MemoryPatch = Field(default_factory=MemoryPatch)


def generate_json_schema() -> dict:
    return SessionUpdate.model_json_schema()


if __name__ == "__main__":
    import json
    from pathlib import Path

    out_path = Path(__file__).resolve().parent.parent / "schemas" / "session_update.schema.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(generate_json_schema(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
