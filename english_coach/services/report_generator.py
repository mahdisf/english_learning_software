"""Human-readable Markdown session and progress reports."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session as OrmSession

from english_coach.models import ItemRevision, LearningItem, MemoryState, Session as SessionModel
from english_coach.services.importer import ImportChangeSet


def render_session_report(db: OrmSession, session: SessionModel, changeset: ImportChangeSet) -> str:
    lines = [f"# Session report — {session.topic}", ""]
    lines.append(f"- Session ID: `{session.id}`")
    lines.append(f"- Type: {session.session_type}")
    lines.append(f"- Ended at: {session.ended_at.isoformat() if session.ended_at else 'unknown'}")
    lines.append("")
    lines.append("## Summary")
    lines.append(session.summary)
    lines.append("")

    if session.strengths:
        lines.append("## Strengths")
        for s in session.strengths:
            lines.append(f"- {s}")
        lines.append("")
    if session.weak_points:
        lines.append("## Weak points")
        for w in session.weak_points:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## New learning items")
    if changeset.new_items:
        for item in changeset.new_items:
            lines.append(f"- **[{item.kind}]** {item.display_text} (`{item.item_id}`)")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## Updated learning items")
    if changeset.updated_items:
        for item in changeset.updated_items:
            change_desc = ", ".join(f"{c.field}" for c in item.scalar_changes) or "no scalar changes"
            lines.append(f"- **[{item.kind}]** {item.display_text} (`{item.item_id}`) — {change_desc}")
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## Mastery / usage changes")
    if changeset.mastery_changes:
        for change in changeset.mastery_changes:
            lines.append(
                f"- {change.display_text}: score {change.old_score} -> {change.new_score}, "
                f"status {change.old_status} -> {change.new_status}"
            )
    else:
        lines.append("_None._")
    lines.append("")

    lines.append("## Memory-state changes")
    mc = changeset.memory_changes
    if mc.topics_added:
        lines.append(f"- Current topics added: {', '.join(mc.topics_added)}")
    if mc.goals_added:
        lines.append(f"- Active goals added: {', '.join(mc.goals_added)}")
    if mc.weak_points_upserted:
        lines.append(f"- Weak points upserted: {', '.join(mc.weak_points_upserted)}")
    if mc.weak_points_resolved:
        lines.append(f"- Weak points resolved: {', '.join(mc.weak_points_resolved)}")
    if mc.next_focus:
        lines.append(f"- Next-session focus: {', '.join(mc.next_focus)}")
    lines.append("")

    lines.append("## Recommended next-session focus")
    if session.next_focus:
        for f in session.next_focus:
            lines.append(f"- {f}")
    else:
        lines.append("_None specified._")
    lines.append("")

    return "\n".join(lines)


def render_progress_report(db: OrmSession) -> str:
    lines = ["# Progress report", ""]
    lines.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    total_sessions = db.query(func.count(SessionModel.id)).scalar() or 0
    lines.append(f"Total sessions recorded: {total_sessions}")
    lines.append("")

    lines.append("## Counts by kind and mastery status")
    rows = (
        db.query(LearningItem.kind, LearningItem.mastery_status, func.count(LearningItem.id))
        .filter(LearningItem.archived_at.is_(None))
        .group_by(LearningItem.kind, LearningItem.mastery_status)
        .all()
    )
    if rows:
        lines.append("| Kind | Status | Count |")
        lines.append("|---|---|---|")
        for kind, status, count in rows:
            lines.append(f"| {kind} | {status} | {count} |")
    else:
        lines.append("_No learning items yet._")
    lines.append("")

    if total_sessions < 3:
        lines.append(
            "> Not enough sessions yet for reliable accuracy trends. "
            "At least 3 sessions are recommended before drawing conclusions."
        )
        lines.append("")

    active_mistakes = (
        db.query(LearningItem)
        .filter(LearningItem.kind == "mistake", LearningItem.archived_at.is_(None))
        .all()
    )
    active_mistakes = [m for m in active_mistakes if m.mistake_detail and m.mistake_detail.state != "resolved"]
    lines.append("## Active recurring mistakes")
    if active_mistakes:
        for m in sorted(active_mistakes, key=lambda x: -x.mistake_detail.occurrence_count):
            lines.append(
                f"- {m.display_text} -> {m.mistake_detail.corrected_sentence} "
                f"(seen {m.mistake_detail.occurrence_count}x, state: {m.mistake_detail.state})"
            )
    else:
        lines.append("_None._")
    lines.append("")

    strongest = (
        db.query(LearningItem)
        .filter(LearningItem.archived_at.is_(None))
        .order_by(LearningItem.mastery_score.desc())
        .limit(10)
        .all()
    )
    lines.append("## Strongest areas")
    for item in strongest:
        lines.append(f"- [{item.kind}] {item.display_text} (mastery {item.mastery_score})")
    lines.append("")

    weakest = (
        db.query(LearningItem)
        .filter(LearningItem.archived_at.is_(None))
        .order_by(LearningItem.mastery_score.asc())
        .limit(10)
        .all()
    )
    lines.append("## Weakest areas")
    for item in weakest:
        lines.append(f"- [{item.kind}] {item.display_text} (mastery {item.mastery_score})")
    lines.append("")

    memory = db.get(MemoryState, 1)
    lines.append("## Recommended focus")
    if memory and memory.next_session_focus:
        for f in memory.next_session_focus:
            lines.append(f"- {f}")
    else:
        lines.append("_None specified._")
    lines.append("")

    return "\n".join(lines)
