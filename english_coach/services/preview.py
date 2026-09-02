"""Rich-based human-readable preview rendering for an import change-set.

All learner/AI-supplied text is escaped with ``rich.markup.escape`` before
being handed to Rich, because Rich normally interprets ``[...]`` in printed
strings and table cells as style markup. Without escaping, content such as
"[Acme Corp]" in an example sentence could be silently swallowed or mis-rendered.
"""
from __future__ import annotations

from rich.console import Console
from rich.markup import escape as esc
from rich.table import Table

from english_coach.services.importer import ImportChangeSet


def render_preview(console: Console, changeset: ImportChangeSet) -> None:
    console.rule(f"[bold]Import preview — session {esc(changeset.session_id)}")
    if not changeset.session_is_new:
        console.print("[yellow]Note:[/yellow] session already existed; session row unchanged.")

    if changeset.new_items:
        table = Table(title=f"New items ({len(changeset.new_items)})")
        table.add_column("Kind")
        table.add_column("Client ref")
        table.add_column("Text")
        table.add_column("Importance")
        table.add_column("CEFR")
        table.add_column("Examples")
        table.add_column("Topics")
        for item in changeset.new_items:
            table.add_row(
                esc(item.kind),
                esc(item.client_ref),
                esc(item.display_text),
                str(item.importance_score),
                esc(item.cefr_level or "-"),
                str(len(item.examples)),
                esc(", ".join(item.topics) or "-"),
            )
        console.print(table)
    else:
        console.print("No new items.")

    if changeset.updated_items:
        table = Table(title=f"Matched / updated items ({len(changeset.updated_items)})")
        table.add_column("Kind")
        table.add_column("Text")
        table.add_column("Field changes")
        table.add_column("New examples")
        table.add_column("New topics")
        for item in changeset.updated_items:
            changes_text = "\n".join(
                f"{esc(c.field)}: {esc(repr(c.old))} -> {esc(repr(c.new))}"
                for c in item.scalar_changes
            ) or "-"
            merged_text = "\n".join(f"{esc(c.field)}: appended" for c in item.merged_list_changes)
            if merged_text:
                changes_text = f"{changes_text}\n{merged_text}" if changes_text != "-" else merged_text
            table.add_row(
                esc(item.kind),
                esc(item.display_text),
                changes_text,
                esc("\n".join(item.appended_examples) or "-"),
                esc(", ".join(item.appended_topics) or "-"),
            )
        console.print(table)
    else:
        console.print("No matched/updated items.")

    if changeset.usage_events:
        qualifying = sum(1 for e in changeset.usage_events if e.qualifying)
        console.print(
            f"Usage events: {len(changeset.usage_events)} total, "
            f"{qualifying} qualifying (affect mastery)."
        )
    else:
        console.print("No usage events.")

    if changeset.mastery_changes:
        table = Table(title="Mastery / counter changes")
        table.add_column("Item")
        table.add_column("Score")
        table.add_column("Status")
        for change in changeset.mastery_changes:
            table.add_row(
                esc(change.display_text),
                f"{change.old_score} -> {change.new_score}",
                f"{esc(change.old_status)} -> {esc(change.new_status)}",
            )
        console.print(table)

    mc = changeset.memory_changes
    if any(
        [
            mc.topics_added,
            mc.topics_removed,
            mc.goals_added,
            mc.goals_removed,
            mc.completed_topics_added,
            mc.weak_points_upserted,
            mc.weak_points_resolved,
            mc.next_focus,
        ]
    ):
        table = Table(title="Memory-state changes")
        table.add_column("Field")
        table.add_column("Value")
        if mc.topics_added:
            table.add_row("current_topics += ", esc(", ".join(mc.topics_added)))
        if mc.topics_removed:
            table.add_row("current_topics -= ", esc(", ".join(mc.topics_removed)))
        if mc.goals_added:
            table.add_row("active_goals += ", esc(", ".join(mc.goals_added)))
        if mc.goals_removed:
            table.add_row("active_goals -= ", esc(", ".join(mc.goals_removed)))
        if mc.completed_topics_added:
            table.add_row("completed_topics += ", esc(", ".join(mc.completed_topics_added)))
        if mc.weak_points_upserted:
            table.add_row("weak_points upserted", esc(", ".join(mc.weak_points_upserted)))
        if mc.weak_points_resolved:
            table.add_row("weak_points resolved", esc(", ".join(mc.weak_points_resolved)))
        if mc.next_focus:
            table.add_row("next_session_focus =", esc(", ".join(mc.next_focus)))
        console.print(table)
    else:
        console.print("No memory-state changes.")

    if changeset.warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for warning in changeset.warnings:
            console.print(f"  - {esc(warning)}")
