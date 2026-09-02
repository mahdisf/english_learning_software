"""Builds the compact/full AI-context export (JSON authoritative, Markdown for humans)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session as OrmSession

from english_coach.models import LearnerProfile, LearningItem, MemoryState, Session as SessionModel

MACHINE_INSTRUCTION = (
    "Reuse every supplied item_id exactly when referring to existing knowledge. "
    "Distinguish language the learner actually produced or recalled from language "
    "the coach merely introduced. Never invent prior sessions, usage, mastery, or "
    "mistakes beyond what is provided here."
)

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class ContextBudget:
    per_category: int = 25
    recent_sessions: int = 5


def _profile_dict(profile: LearnerProfile | None) -> dict:
    if profile is None:
        return {}
    return {
        "native_language": profile.native_language,
        "current_level": profile.current_level,
        "target_level": profile.target_level,
        "english_variety": profile.english_variety,
        "pronunciation_standard": profile.pronunciation_standard,
        "daily_study_minutes": profile.daily_study_minutes,
        "persian_meaning_policy": profile.persian_meaning_policy,
        "professional_background": profile.professional_background,
        "learning_goals": profile.learning_goals,
    }


def _item_public_dict(item: LearningItem) -> dict:
    base = {
        "item_id": item.id,
        "kind": item.kind,
        "display_text": item.display_text,
        "cefr_level": item.cefr_level,
        "importance_score": item.importance_score,
        "mastery_score": item.mastery_score,
        "mastery_status": item.manual_mastery_override or item.mastery_status,
        "mastery_overridden": item.manual_mastery_override is not None,
        "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
    }
    detail = (
        item.vocabulary_detail or item.expression_detail or item.grammar_detail or item.mistake_detail
    )
    if item.kind == "vocabulary" and detail is not None:
        base.update(
            {
                "lemma": detail.lemma,
                "part_of_speech": detail.part_of_speech,
                "meaning_english": detail.meaning_english,
                "meaning_persian": detail.meaning_persian,
            }
        )
    elif item.kind == "expression" and detail is not None:
        base.update(
            {
                "expression_type": detail.expression_type,
                "meaning_english": detail.meaning_english,
                "meaning_persian": detail.meaning_persian,
            }
        )
    elif item.kind == "grammar" and detail is not None:
        base.update({"structure": detail.structure, "explanation_english": detail.explanation_english})
    elif item.kind == "mistake" and detail is not None:
        base.update(
            {
                "corrected_sentence": detail.corrected_sentence,
                "severity": detail.severity,
                "state": detail.state,
                "occurrence_count": detail.occurrence_count,
            }
        )
    return base


def _non_mastered_items(db: OrmSession, kind: str, limit: int | None) -> list[LearningItem]:
    query = (
        db.query(LearningItem)
        .filter(LearningItem.kind == kind, LearningItem.archived_at.is_(None))
        .filter(LearningItem.mastery_status != "mastered")
        .order_by(
            desc(LearningItem.importance_score),
            LearningItem.mastery_score.asc(),
            desc(LearningItem.updated_at),
        )
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def _recent_items(db: OrmSession, kind: str, limit: int) -> list[LearningItem]:
    return (
        db.query(LearningItem)
        .filter(LearningItem.kind == kind, LearningItem.archived_at.is_(None))
        .order_by(desc(LearningItem.first_learned_at))
        .limit(limit)
        .all()
    )


def build_context(
    db: OrmSession, *, full: bool = False, budget: ContextBudget | None = None
) -> dict:
    budget = budget or ContextBudget()
    profile = db.get(LearnerProfile, 1)
    memory = db.get(MemoryState, 1)

    recent_sessions = (
        db.query(SessionModel)
        .order_by(desc(SessionModel.ended_at))
        .limit(budget.recent_sessions)
        .all()
    )

    mistakes_query = (
        db.query(LearningItem)
        .filter(LearningItem.kind == "mistake", LearningItem.archived_at.is_(None))
    )
    mistakes = mistakes_query.all()
    mistakes = [m for m in mistakes if m.mistake_detail and m.mistake_detail.state != "resolved"]
    mistakes.sort(
        key=lambda m: (
            _SEVERITY_ORDER.get(m.mistake_detail.severity, 3),
            -m.mistake_detail.occurrence_count,
            -(m.last_used_at.timestamp() if m.last_used_at else 0),
        )
    )

    limit = None if full else budget.per_category
    vocab_items = _non_mastered_items(db, "vocabulary", limit)
    expr_items = _non_mastered_items(db, "expression", limit)
    grammar_items = _non_mastered_items(db, "grammar", limit)
    if not full:
        mistakes_included = mistakes[:limit]
    else:
        mistakes_included = mistakes

    recall_candidates = _recent_items(db, "vocabulary", 5 if not full else 999999)

    total_active_counts = {
        "vocabulary": db.query(LearningItem)
        .filter(LearningItem.kind == "vocabulary", LearningItem.archived_at.is_(None))
        .count(),
        "expression": db.query(LearningItem)
        .filter(LearningItem.kind == "expression", LearningItem.archived_at.is_(None))
        .count(),
        "grammar": db.query(LearningItem)
        .filter(LearningItem.kind == "grammar", LearningItem.archived_at.is_(None))
        .count(),
        "mistake": len(mistakes),
    }

    omitted_counts = {
        "vocabulary": max(0, total_active_counts["vocabulary"] - len(vocab_items)),
        "expression": max(0, total_active_counts["expression"] - len(expr_items)),
        "grammar": max(0, total_active_counts["grammar"] - len(grammar_items)),
        "mistake": max(0, total_active_counts["mistake"] - len(mistakes_included)),
    }

    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "full" if full else "compact",
        "learner_profile": _profile_dict(profile),
        "active_goals": memory.active_goals if memory else [],
        "active_weak_points": memory.weak_points if memory else [],
        "next_session_focus": memory.next_session_focus if memory else [],
        "recent_sessions": [
            {
                "session_id": s.id,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "topic": s.topic,
                "session_type": s.session_type,
                "summary": s.summary,
                "next_focus": s.next_focus,
            }
            for s in recent_sessions
        ],
        "unresolved_mistakes": [_item_public_dict(m) for m in mistakes_included],
        "priority_vocabulary": [_item_public_dict(i) for i in vocab_items],
        "priority_expressions": [_item_public_dict(i) for i in expr_items],
        "priority_grammar": [_item_public_dict(i) for i in grammar_items],
        "recent_for_active_recall": [_item_public_dict(i) for i in recall_candidates],
        "omitted_counts": omitted_counts,
        "instruction": MACHINE_INSTRUCTION,
    }
    return context


def render_context_markdown(context: dict) -> str:
    lines = ["# AI Context Export", ""]
    lines.append(f"Generated at: {context['generated_at']} ({context['mode']})")
    lines.append("")
    profile = context.get("learner_profile", {})
    lines.append("## Learner profile")
    for key, value in profile.items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")
    lines.append("## Active goals")
    for goal in context.get("active_goals", []):
        lines.append(f"- {goal}")
    lines.append("")
    lines.append("## Active weak points")
    for wp in context.get("active_weak_points", []):
        lines.append(f"- `{wp.get('key')}`: {wp.get('description')} (severity: {wp.get('severity')})")
    lines.append("")
    lines.append("## Next-session focus")
    for focus in context.get("next_session_focus", []):
        lines.append(f"- {focus}")
    lines.append("")
    lines.append("## Recent sessions")
    for s in context.get("recent_sessions", []):
        lines.append(f"- **{s['topic']}** ({s['session_type']}, {s['ended_at']}): {s['summary']}")
    lines.append("")
    lines.append("## Unresolved / recurring mistakes")
    for m in context.get("unresolved_mistakes", []):
        lines.append(f"- [{m['item_id']}] {m['display_text']} -> {m.get('corrected_sentence')}")
    lines.append("")
    lines.append("## Priority vocabulary")
    for v in context.get("priority_vocabulary", []):
        lines.append(f"- [{v['item_id']}] {v['display_text']} (mastery {v['mastery_score']})")
    lines.append("")
    lines.append("## Priority expressions")
    for v in context.get("priority_expressions", []):
        lines.append(f"- [{v['item_id']}] {v['display_text']} (mastery {v['mastery_score']})")
    lines.append("")
    lines.append("## Priority grammar")
    for v in context.get("priority_grammar", []):
        lines.append(f"- [{v['item_id']}] {v['display_text']} (mastery {v['mastery_score']})")
    lines.append("")
    lines.append("## Recently learned (active recall candidates)")
    for v in context.get("recent_for_active_recall", []):
        lines.append(f"- [{v['item_id']}] {v['display_text']}")
    lines.append("")
    counts = context.get("omitted_counts", {})
    lines.append("## Omitted material (not included above)")
    for key, value in counts.items():
        lines.append(f"- {key}: {value} additional item(s) not shown")
    lines.append("")
    lines.append("## Instruction for the AI")
    lines.append(context.get("instruction", ""))
    lines.append("")
    return "\n".join(lines)
