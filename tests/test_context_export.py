from pathlib import Path

from english_coach.services.context_exporter import ContextBudget, build_context
from english_coach.services.importer import execute_import, load_session_update

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = REPO_ROOT / "examples" / "session_update.example.json"


def test_compact_context_has_stable_ids_and_no_transcript(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    context = build_context(db_session, full=False, budget=ContextBudget(per_category=10, recent_sessions=5))

    assert context["mode"] == "compact"
    assert context["learner_profile"]["native_language"] == "Persian"
    assert context["active_goals"]
    assert context["recent_sessions"][0]["topic"] == "Leading a project status meeting"

    all_items = (
        context["priority_vocabulary"]
        + context["priority_expressions"]
        + context["priority_grammar"]
        + context["unresolved_mistakes"]
    )
    assert all_items
    for item in all_items:
        assert "item_id" in item and len(item["item_id"]) == 36

    # The context never includes a raw transcript field.
    serialized_keys = set(context.keys())
    assert "transcript" not in serialized_keys
    for session in context["recent_sessions"]:
        assert "transcript" not in session

    assert "instruction" in context and "reuse" in context["instruction"].lower()


def test_full_context_includes_more_than_compact(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    compact = build_context(db_session, full=False, budget=ContextBudget(per_category=0, recent_sessions=5))
    full = build_context(db_session, full=True, budget=ContextBudget(per_category=0, recent_sessions=5))

    assert len(full["priority_vocabulary"]) >= len(compact["priority_vocabulary"])
    assert full["mode"] == "full"
