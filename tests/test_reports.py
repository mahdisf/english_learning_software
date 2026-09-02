from pathlib import Path

from english_coach.services.importer import execute_import, load_session_update
from english_coach.services.report_generator import render_progress_report, render_session_report
from english_coach.models import Session as SessionModel

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = REPO_ROOT / "examples" / "session_update.example.json"


def test_session_report_contains_key_sections(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    session_row = db_session.get(SessionModel, execution.changeset.session_id)
    markdown = render_session_report(db_session, session_row, execution.changeset)

    assert "Leading a project status meeting" in markdown
    assert "mitigate" in markdown
    assert "New learning items" in markdown
    assert "Memory-state changes" in markdown
    # No full transcript should ever appear; only the stored summary text.
    assert payload.session.summary in markdown


def test_progress_report_states_limitation_with_few_sessions(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    markdown = render_progress_report(db_session)
    assert "Not enough sessions" in markdown
    assert "mitigate" in markdown or "Strongest areas" in markdown
