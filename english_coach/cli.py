"""Typer CLI for the English Coach knowledge system."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session as OrmSession

from english_coach.config import Settings, get_settings
from english_coach.db import DatabaseNotInitializedError, get_session_factory, require_database
from english_coach.migrate import seed_singletons, upgrade_to_head
from english_coach.models import LearningItem, Session as SessionModel
from english_coach.services import anki_exporter, backup as backup_service, context_exporter
from english_coach.services import report_generator, search as search_service
from english_coach.services.deduplication import ReferenceError_
from english_coach.services.importer import (
    ImportConflictError,
    ImportValidationError,
    execute_import,
    load_session_update,
)
from english_coach.services.preview import render_preview
from english_coach.atomic_io import atomic_write_text

app = typer.Typer(add_completion=False, help="Local AI-powered personal English coach knowledge system.")
export_app = typer.Typer(help="Export AI context or Anki packages.")
report_app = typer.Typer(help="Human-readable reports.")
item_app = typer.Typer(help="Inspect individual learning items.")
app.add_typer(export_app, name="export")
app.add_typer(report_app, name="report")
app.add_typer(item_app, name="item")

console = Console()

DEBUG_FLAG = {"value": False}


def _fail(message: str, exit_code: int = 1) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")
    raise typer.Exit(code=exit_code)


def _handle_unexpected(exc: Exception) -> None:
    if DEBUG_FLAG["value"]:
        raise exc
    _fail(str(exc))


@app.callback()
def main(debug: bool = typer.Option(False, "--debug", help="Show full tracebacks on error.")):
    DEBUG_FLAG["value"] = debug


def _settings() -> Settings:
    return get_settings()


def _open_session(settings: Settings) -> OrmSession:
    try:
        require_database(settings)
    except DatabaseNotInitializedError as exc:
        _fail(str(exc))
    factory = get_session_factory(settings)
    return factory()


@app.command()
def init():
    """Create directories, apply migrations, and seed singleton rows. Safe to re-run."""
    settings = _settings()
    db_existed = settings.database_path.is_file()

    for directory in (
        settings.database_path.parent,
        settings.imported_dir,
        settings.backups_dir,
        settings.exports_dir,
        settings.reports_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    if db_existed:
        try:
            backup_service.create_backup(settings, label="pre_migrate")
        except Exception as exc:  # pragma: no cover - best effort safety net
            console.print(f"[yellow]Warning:[/yellow] could not create pre-migration backup: {exc}")

    try:
        upgrade_to_head(settings)
    except Exception as exc:
        _handle_unexpected(exc)
        return

    seed_singletons(settings)
    console.print(f"[green]Initialized.[/green] Database at {settings.database_path}")


@app.command()
def backup():
    """Create a timestamped, consistent SQLite backup."""
    settings = _settings()
    try:
        require_database(settings)
    except DatabaseNotInitializedError as exc:
        _fail(str(exc))
    path = backup_service.create_backup(settings)
    console.print(f"[green]Backup written to[/green] {path}")


@app.command()
def validate(path: Path):
    """Parse, schema-validate, and check references for a session-update JSON file. No mutation."""
    settings = _settings()
    if not path.is_file():
        _fail(f"File not found: {path}")

    raw_bytes = path.read_bytes()
    try:
        payload, canonical_text, content_hash = load_session_update(raw_bytes)
    except ImportValidationError as exc:
        console.print("[bold red]Validation failed:[/bold red]")
        for err in exc.errors:
            console.print(f"  - {err}")
        raise typer.Exit(code=1)

    db = _open_session(settings)
    try:
        execution = execute_import(db, payload, canonical_text, content_hash, path.name)
        if execution.idempotent:
            assert execution.batch is not None
            console.print(
                f"[yellow]This update was already imported[/yellow] "
                f"(batch {execution.batch.id}, applied {execution.batch.applied_at})."
            )
        else:
            assert execution.changeset is not None
            render_preview(console, execution.changeset)
            console.print(
                "[green]Validation succeeded.[/green] No changes were applied (validate never mutates)."
            )
    except (ImportValidationError, ImportConflictError, ReferenceError_) as exc:
        db.rollback()
        console.print(f"[bold red]Validation failed:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except Exception as exc:
        db.rollback()
        _handle_unexpected(exc)
    else:
        db.rollback()
    finally:
        db.close()


@app.command(name="import")
def import_cmd(
    path: Path,
    yes: bool = typer.Option(
        False, "--yes", help="Skip the confirmation prompt (still prints the preview). Risky for automation."
    ),
):
    """Validate, preview, and (after approval) atomically import a session-update JSON file."""
    settings = _settings()
    if not path.is_file():
        _fail(f"File not found: {path}")

    raw_bytes = path.read_bytes()
    try:
        payload, canonical_text, content_hash = load_session_update(raw_bytes)
    except ImportValidationError as exc:
        console.print("[bold red]Validation failed:[/bold red]")
        for err in exc.errors:
            console.print(f"  - {err}")
        raise typer.Exit(code=1)

    db = _open_session(settings)
    try:
        execution = execute_import(db, payload, canonical_text, content_hash, path.name)
    except (ImportValidationError, ImportConflictError, ReferenceError_) as exc:
        db.rollback()
        db.close()
        console.print(f"[bold red]Import rejected:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except Exception as exc:
        db.rollback()
        db.close()
        _handle_unexpected(exc)
        return

    if execution.idempotent:
        assert execution.batch is not None
        db.rollback()
        db.close()
        console.print(
            f"[yellow]No changes applied.[/yellow] This update was already imported "
            f"(batch {execution.batch.id}, applied {execution.batch.applied_at})."
        )
        return

    assert execution.changeset is not None
    render_preview(console, execution.changeset)

    approved = yes or typer.confirm("Apply all displayed changes?", default=False)
    if not approved:
        db.rollback()
        db.close()
        console.print("[yellow]No changes applied.[/yellow]")
        return

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        db.close()
        _handle_unexpected(exc)
        return

    session_row = db.get(SessionModel, execution.changeset.session_id)
    assert session_row is not None
    report_markdown = report_generator.render_session_report(db, session_row, execution.changeset)
    db.close()
    assert execution.batch is not None

    imported_path = settings.imported_dir / f"{payload.update_id}.json"
    atomic_write_text(imported_path, canonical_text)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = settings.reports_dir / f"session_{timestamp}_{str(payload.session.session_id)[:8]}.md"
    atomic_write_text(report_path, report_markdown)

    console.print(f"[green]Import applied successfully.[/green] Batch: {execution.batch.id}")
    console.print(f"Raw JSON copied to {imported_path}")
    console.print(f"Session report written to {report_path}")


@export_app.command("ai-context")
def export_ai_context(full: bool = typer.Option(False, "--full", help="Include every non-archived item.")):
    """Export the compact (default) or full AI-context JSON + Markdown."""
    settings = _settings()
    db = _open_session(settings)
    try:
        budget = context_exporter.ContextBudget(
            per_category=settings.context_export.default_item_budget,
            recent_sessions=settings.context_export.recent_session_count,
        )
        context = context_exporter.build_context(db, full=full, budget=budget)
    finally:
        db.close()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = settings.exports_dir / f"ai_context_{timestamp}.json"
    md_path = settings.exports_dir / f"ai_context_{timestamp}.md"

    atomic_write_text(json_path, json.dumps(context, indent=2, ensure_ascii=False))
    atomic_write_text(md_path, context_exporter.render_context_markdown(context))

    console.print(f"[green]AI context exported.[/green]\nJSON: {json_path}\nMarkdown: {md_path}")
    if full:
        console.print("[yellow]Note:[/yellow] --full may be large; it includes every non-archived item.")


def _parse_date(value: Optional[str], label: str) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(f"Invalid {label} date: {value!r}. Use YYYY-MM-DD.")


@export_app.command("anki")
def export_anki(
    from_: Optional[str] = typer.Option(None, "--from", help="Inclusive start date (YYYY-MM-DD, local)."),
    to: Optional[str] = typer.Option(None, "--to", help="Inclusive end date (YYYY-MM-DD, local)."),
    all_: bool = typer.Option(False, "--all", help="Include all matching items, even if already exported."),
    format_: str = typer.Option("apkg", "--format", help="Output format: apkg (default) or tsv."),
):
    """Export pending learning items as an Anki .apkg (default) or TSV fallback."""
    settings = _settings()
    date_from = _parse_date(from_, "--from")
    date_to = _parse_date(to, "--to")
    if date_from is not None and date_to is not None and date_from > date_to:
        _fail("--from must not be later than --to.")

    db = _open_session(settings)
    try:
        if format_ == "apkg":
            result = anki_exporter.export_apkg(
                db, settings, date_from=date_from, date_to=date_to, include_all=all_
            )
        elif format_ == "tsv":
            result = anki_exporter.export_tsv(
                db, settings, date_from=date_from, date_to=date_to, include_all=all_
            )
        else:
            _fail(f"Unknown format: {format_!r}. Use 'apkg' or 'tsv'.")
            return
    except ValueError as exc:
        db.rollback()
        _fail(str(exc))
        return
    except Exception as exc:
        db.rollback()
        _handle_unexpected(exc)
        return
    finally:
        db.close()

    if not result.written:
        console.print(f"[yellow]{result.message}[/yellow]")
        return
    console.print(f"[green]{result.message}[/green]")
    console.print("Assumed imported into Anki/AnkiDroid; pending state is now cleared for these items.")


@report_app.command("latest")
def report_latest():
    """Show the most recently generated session report."""
    settings = _settings()
    reports = sorted(settings.reports_dir.glob("session_*.md"), reverse=True)
    if not reports:
        console.print("[yellow]No session reports found yet.[/yellow]")
        return
    console.print(reports[0].read_text(encoding="utf-8"), markup=False, highlight=False)


@report_app.command("session")
def report_session(session_id: str):
    """Regenerate a report for a specific session ID from current data."""
    settings = _settings()
    db = _open_session(settings)
    try:
        session_row = db.get(SessionModel, session_id)
        if session_row is None:
            _fail(f"Session not found: {session_id}")
            return
        from english_coach.services.importer import ImportChangeSet

        empty_changeset = ImportChangeSet(update_id="", session_id=session_id, session_is_new=False)
        markdown = report_generator.render_session_report(db, session_row, empty_changeset)
        console.print(markdown, markup=False, highlight=False)
    finally:
        db.close()


@report_app.command("progress")
def report_progress():
    """Show the progress report (counts, trends, mistakes, strong/weak areas)."""
    settings = _settings()
    db = _open_session(settings)
    try:
        markdown = report_generator.render_progress_report(db)
        console.print(markdown, markup=False, highlight=False)
    finally:
        db.close()


@app.command()
def search(query: str):
    """Search display text, meanings, examples, tags, structures, and mistake sentences."""
    settings = _settings()
    db = _open_session(settings)
    try:
        results = search_service.search_items(db, query)
        if not results:
            console.print("[yellow]No matches found.[/yellow]")
            return
        from rich.markup import escape as esc

        table = Table(title=f"Search results for '{esc(query)}'")
        table.add_column("Kind")
        table.add_column("Text")
        table.add_column("Item ID")
        table.add_column("Mastery")
        for item in results:
            table.add_row(
                item.kind, esc(item.display_text), item.id,
                f"{item.mastery_score} ({item.mastery_status})",
            )
        console.print(table)
    finally:
        db.close()


@item_app.command("show")
def item_show(item_id: str):
    """Show full details for a single learning item."""
    settings = _settings()
    db = _open_session(settings)
    try:
        from rich.markup import escape as esc

        item = db.get(LearningItem, item_id)
        if item is None:
            _fail(f"Item not found: {item_id}")
            return
        console.print(f"[bold]{esc(item.display_text)}[/bold] ({item.kind})")
        console.print(f"ID: {item.id}")
        console.print(f"CEFR: {item.cefr_level or '-'}   Importance: {item.importance_score}")
        console.print(
            f"Mastery: {item.mastery_score} ({item.manual_mastery_override or item.mastery_status})"
        )
        console.print(f"Usage: {item.usage_count_correct}/{item.usage_count_total} correct")
        detail = (
            item.vocabulary_detail or item.expression_detail or item.grammar_detail or item.mistake_detail
        )
        if detail is not None:
            for col in detail.__table__.columns:
                if col.name == "item_id":
                    continue
                console.print(f"  {col.name}: {esc(str(getattr(detail, col.name)))}")
        if item.examples:
            console.print("Examples:")
            for ex in item.examples:
                console.print(f"  - {esc(ex.sentence)}")
    finally:
        db.close()


if __name__ == "__main__":
    app()
