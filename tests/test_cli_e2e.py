import shutil
from pathlib import Path

from typer.testing import CliRunner

from english_coach.cli import app

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = REPO_ROOT / "examples" / "session_update.example.json"

runner = CliRunner()


def test_init_is_idempotent(cli_project):
    result1 = runner.invoke(app, ["init"])
    assert result1.exit_code == 0, result1.output
    assert (cli_project / "data" / "english_coach.db").is_file()

    result2 = runner.invoke(app, ["init"])
    assert result2.exit_code == 0, result2.output


def test_full_workflow_validate_import_report_context_anki(cli_project):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output

    example_copy = cli_project / "session_update.json"
    shutil.copy(EXAMPLE_PATH, example_copy)

    validate_result = runner.invoke(app, ["validate", str(example_copy)])
    assert validate_result.exit_code == 0, validate_result.output
    assert "Validation succeeded" in validate_result.output

    import_result = runner.invoke(app, ["import", str(example_copy), "--yes"])
    assert import_result.exit_code == 0, import_result.output
    assert "Import applied successfully" in import_result.output

    imported_files = list((cli_project / "data" / "imported").glob("*.json"))
    assert imported_files

    search_result = runner.invoke(app, ["search", "mitigate"])
    assert search_result.exit_code == 0, search_result.output
    assert "mitigate" in search_result.output

    report_result = runner.invoke(app, ["report", "latest"])
    assert report_result.exit_code == 0, report_result.output
    assert "Leading a project status meeting" in report_result.output

    progress_result = runner.invoke(app, ["report", "progress"])
    assert progress_result.exit_code == 0, progress_result.output

    context_result = runner.invoke(app, ["export", "ai-context"])
    assert context_result.exit_code == 0, context_result.output
    exported_json = list((cli_project / "exports").glob("ai_context_*.json"))
    assert exported_json

    anki_result = runner.invoke(app, ["export", "anki"])
    assert anki_result.exit_code == 0, anki_result.output
    exported_apkg = list((cli_project / "exports").glob("*.apkg"))
    assert exported_apkg
    assert exported_apkg[0].stat().st_size > 0


def test_import_without_confirmation_makes_no_changes(cli_project):
    runner.invoke(app, ["init"])
    example_copy = cli_project / "session_update.json"
    shutil.copy(EXAMPLE_PATH, example_copy)

    result = runner.invoke(app, ["import", str(example_copy)], input="n\n")
    assert result.exit_code == 0, result.output
    assert "No changes applied" in result.output

    search_result = runner.invoke(app, ["search", "mitigate"])
    assert "No matches found" in search_result.output


def test_item_show_and_report_session_and_tsv_export(cli_project):
    runner.invoke(app, ["init"])
    example_copy = cli_project / "session_update.json"
    shutil.copy(EXAMPLE_PATH, example_copy)
    import_result = runner.invoke(app, ["import", str(example_copy), "--yes"])
    assert import_result.exit_code == 0, import_result.output

    from english_coach.config import get_settings
    from english_coach.db import get_session_factory
    from english_coach.models import LearningItem

    settings = get_settings()
    factory = get_session_factory(settings)
    db = factory()
    try:
        item_id = (
            db.query(LearningItem.id)
            .filter(LearningItem.display_text == "mitigate")
            .scalar()
        )
    finally:
        db.close()
    assert item_id

    show_result = runner.invoke(app, ["item", "show", item_id])
    assert show_result.exit_code == 0, show_result.output
    assert "mitigate" in show_result.output

    import json

    session_id = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))["session"]["session_id"]
    session_report_result = runner.invoke(app, ["report", "session", session_id])
    assert session_report_result.exit_code == 0, session_report_result.output
    assert "Leading a project status meeting" in session_report_result.output

    tsv_result = runner.invoke(app, ["export", "anki", "--format", "tsv"])
    assert tsv_result.exit_code == 0, tsv_result.output
    tsv_files = list((cli_project / "exports").glob("*.tsv"))
    assert tsv_files


def test_anki_export_invalid_date_range_cli(cli_project):
    runner.invoke(app, ["init"])
    result = runner.invoke(
        app, ["export", "anki", "--from", "2026-06-01", "--to", "2026-01-01"]
    )
    assert result.exit_code != 0
    assert "must not be later than" in result.output


def test_backup_command(cli_project):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0, result.output
    backups = list((cli_project / "data" / "backups").glob("*.db"))
    assert backups
