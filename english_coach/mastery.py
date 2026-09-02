"""Mastery-score and status computation.

Mastery represents observed conversational production and recall. It is
deliberately unrelated to Anki scheduling algorithms (intervals, ease
factors, due dates).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualifyingEvent:
    session_id: str
    correct: bool


@dataclass(frozen=True)
class MasteryResult:
    score: int
    status: str


def compute_mastery(events: list[QualifyingEvent]) -> MasteryResult:
    """Compute the mastery score/status from qualifying usage events.

    Only ``user_production`` and ``prompted_recall`` events with non-null
    correctness qualify; filtering must happen before calling this function.
    """
    count = len(events)
    if count == 0:
        return MasteryResult(score=0, status="new")

    correct_count = sum(1 for e in events if e.correct)
    accuracy = correct_count / count
    accuracy_component = round(50 * accuracy)
    volume_component = min(30, count * 3)
    distinct_sessions = len({e.session_id for e in events})
    session_component = min(20, distinct_sessions * 4)
    score = accuracy_component + volume_component + session_component

    status = _status_for(score, count, distinct_sessions, accuracy, events)
    return MasteryResult(score=score, status=status)


def _status_for(
    score: int,
    count: int,
    distinct_sessions: int,
    accuracy: float,
    events: list[QualifyingEvent],
) -> str:
    last_three_correct = len(events) >= 3 and all(e.correct for e in events[-3:])
    if (
        score >= 90
        and count >= 12
        and distinct_sessions >= 5
        and accuracy >= 0.90
        and last_three_correct
    ):
        return "mastered"
    if score >= 70:
        return "strong"
    if score >= 40:
        return "practicing"
    if score >= 1:
        return "learning"
    return "new"


def mistake_state(
    correct_attempts_since_last_occurrence: int,
    distinct_sessions_since_last_occurrence: int,
    manual_override: str | None = None,
) -> str:
    """Determine a mistake's lifecycle state.

    Resolved requires at least five correct qualifying attempts across at
    least three sessions since the most recent occurrence, or an explicit
    human override.
    """
    if manual_override in ("active", "improving", "resolved"):
        return manual_override
    if correct_attempts_since_last_occurrence >= 5 and distinct_sessions_since_last_occurrence >= 3:
        return "resolved"
    if correct_attempts_since_last_occurrence > 0:
        return "improving"
    return "active"
