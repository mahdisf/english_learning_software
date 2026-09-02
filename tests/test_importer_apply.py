import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from english_coach.models import (
    ImportBatch,
    ItemRevision,
    LearningItem,
    MemoryState,
    UsageEvent,
)
from english_coach.services.importer import (
    ImportConflictError,
    ImportValidationError,
    execute_import,
    load_session_update,
)
from english_coach.services.deduplication import ReferenceError_

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = REPO_ROOT / "examples" / "session_update.example.json"


def _load_example_dict() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def _bytes_from_dict(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


def test_preview_only_does_not_mutate(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    assert execution.changeset.new_items
    db_session.rollback()

    assert db_session.query(LearningItem).count() == 0
    assert db_session.query(ImportBatch).count() == 0


def test_successful_atomic_import_creates_all_kinds(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    kinds = {row.kind for row in db_session.query(LearningItem).all()}
    assert kinds == {"vocabulary", "expression", "grammar", "mistake"}
    assert db_session.query(ImportBatch).count() == 1
    assert len(execution.changeset.new_items) == 5


def test_duplicate_update_id_and_hash_is_idempotent(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()
    item_count_after_first = db_session.query(LearningItem).count()

    payload2, canonical_text2, content_hash2 = load_session_update(raw)
    execution2 = execute_import(db_session, payload2, canonical_text2, content_hash2, "example.json")
    db_session.rollback()

    assert execution2.idempotent is True
    assert db_session.query(LearningItem).count() == item_count_after_first


def test_same_update_id_different_content_is_rejected(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    obj = _load_example_dict()
    obj["session"]["summary"] = "A materially different summary."
    modified_bytes = _bytes_from_dict(obj)
    payload2, canonical_text2, content_hash2 = load_session_update(modified_bytes)

    with pytest.raises(ImportConflictError):
        execute_import(db_session, payload2, canonical_text2, content_hash2, "example2.json")
    db_session.rollback()


def test_known_item_id_upsert(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    mitigate_item_id = next(
        i.item_id for i in execution.changeset.new_items if i.display_text == "mitigate"
    )

    obj = _load_example_dict()
    obj["update_id"] = str(uuid.uuid4())
    obj["session"]["session_id"] = str(uuid.uuid4())
    obj["session"]["summary"] = "Follow-up session reusing mitigate."
    vocab_entry = obj["vocabulary"][0]
    vocab_entry["item_id"] = mitigate_item_id
    vocab_entry["importance_score"] = 10
    vocab_entry["usage_note"] = "Updated usage note from follow-up session."
    obj["vocabulary"] = [vocab_entry]
    obj["expressions"] = []
    obj["grammar_patterns"] = []
    obj["mistakes"] = []
    obj["usage_events"] = [
        e for e in obj["usage_events"] if e.get("client_ref") == vocab_entry["client_ref"]
    ]
    obj["usage_events"][0]["event_id"] = str(uuid.uuid4())

    payload2, canonical_text2, content_hash2 = load_session_update(_bytes_from_dict(obj))
    execution2 = execute_import(db_session, payload2, canonical_text2, content_hash2, "followup.json")
    db_session.commit()

    assert len(execution2.changeset.updated_items) == 1
    updated = execution2.changeset.updated_items[0]
    assert updated.item_id == mitigate_item_id

    item = db_session.get(LearningItem, mitigate_item_id)
    assert item.importance_score == 10
    assert item.vocabulary_detail.usage_note == "Updated usage note from follow-up session."
    assert item.revision == 2

    revisions = (
        db_session.query(ItemRevision).filter(ItemRevision.item_id == mitigate_item_id).all()
    )
    assert len(revisions) == 2  # one for creation, one for the update


def test_ambiguous_same_file_new_items_rejected(db_session):
    obj = _load_example_dict()
    duplicate_entry = copy.deepcopy(obj["vocabulary"][0])
    duplicate_entry["client_ref"] = "vocab_mitigate_dup"
    obj["vocabulary"].append(duplicate_entry)
    obj["usage_events"] = []

    payload, canonical_text, content_hash = load_session_update(_bytes_from_dict(obj))
    with pytest.raises(ImportValidationError):
        execute_import(db_session, payload, canonical_text, content_hash, "dup.json")
    db_session.rollback()


def test_client_ref_resolution_for_usage_events(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    events = db_session.query(UsageEvent).all()
    assert len(events) == 4
    item_ids = {i.id for i in db_session.query(LearningItem).all()}
    assert all(e.item_id in item_ids for e in events)


def test_usage_event_with_unknown_client_ref_rejected(db_session):
    obj = _load_example_dict()
    obj["usage_events"][0]["client_ref"] = "does_not_exist"
    payload, canonical_text, content_hash = load_session_update(_bytes_from_dict(obj))
    with pytest.raises(ReferenceError_):
        execute_import(db_session, payload, canonical_text, content_hash, "bad.json")
    db_session.rollback()


def test_usage_counters_ignore_coach_introduction(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    mitigate_item_id = next(
        i.item_id for i in execution.changeset.new_items if i.display_text == "mitigate"
    )
    item = db_session.get(LearningItem, mitigate_item_id)
    # 'mitigate' only had a coach_introduction event, which must not count as usage.
    assert item.usage_count_total == 0
    assert item.mastery_score == 0
    assert item.mastery_status == "new"

    delegate_item_id = next(
        i.item_id for i in execution.changeset.new_items if i.display_text == "delegate"
    )
    delegate_item = db_session.get(LearningItem, delegate_item_id)
    assert delegate_item.usage_count_total == 1
    assert delegate_item.usage_count_correct == 1


def test_scalar_and_example_changes_appear_in_preview(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()
    mitigate_item_id = next(
        i.item_id for i in execution.changeset.new_items if i.display_text == "mitigate"
    )

    obj = _load_example_dict()
    obj["update_id"] = str(uuid.uuid4())
    obj["session"]["session_id"] = str(uuid.uuid4())
    vocab_entry = obj["vocabulary"][0]
    vocab_entry["item_id"] = mitigate_item_id
    vocab_entry["usage_note"] = "Brand-new usage note."
    vocab_entry["examples"] = ["A totally new example sentence for mitigate."]
    obj["vocabulary"] = [vocab_entry]
    obj["expressions"] = []
    obj["grammar_patterns"] = []
    obj["mistakes"] = []
    obj["usage_events"] = []

    payload2, canonical_text2, content_hash2 = load_session_update(_bytes_from_dict(obj))
    execution2 = execute_import(db_session, payload2, canonical_text2, content_hash2, "u2.json")
    db_session.commit()

    updated = execution2.changeset.updated_items[0]
    changed_fields = {c.field for c in updated.scalar_changes}
    assert "usage_note" in changed_fields
    assert "A totally new example sentence for mitigate." in updated.appended_examples


def test_memory_patch_singleton_merge(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()

    memory = db_session.get(MemoryState, 1)
    assert "leadership meetings" in memory.current_topics
    assert "Lead a status meeting confidently in English" in memory.active_goals
    assert any(wp["key"] == "articles-before-role-nouns" for wp in memory.weak_points)
    assert memory.next_session_focus == payload.memory_patch.next_session_focus

    # Second import resolves the weak point and adds a new topic; must merge, not replace.
    obj = _load_example_dict()
    obj["update_id"] = str(uuid.uuid4())
    obj["session"]["session_id"] = str(uuid.uuid4())
    obj["vocabulary"] = []
    obj["expressions"] = []
    obj["grammar_patterns"] = []
    obj["mistakes"] = []
    obj["usage_events"] = []
    obj["memory_patch"]["current_topics_add"] = ["interview preparation"]
    obj["memory_patch"]["weak_points_resolved"] = ["articles-before-role-nouns"]
    obj["memory_patch"]["weak_points_upsert"] = []

    payload2, canonical_text2, content_hash2 = load_session_update(_bytes_from_dict(obj))
    execute_import(db_session, payload2, canonical_text2, content_hash2, "u2.json")
    db_session.commit()

    memory = db_session.get(MemoryState, 1)
    assert "leadership meetings" in memory.current_topics
    assert "interview preparation" in memory.current_topics
    assert not any(wp["key"] == "articles-before-role-nouns" for wp in memory.weak_points)


def test_forced_mid_import_failure_rolls_back_everything(db_session, monkeypatch):
    from english_coach.services import importer as importer_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure during memory patch application")

    monkeypatch.setattr(importer_module, "_merge_list", _boom)

    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    with pytest.raises(RuntimeError):
        execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.rollback()

    assert db_session.query(LearningItem).count() == 0
    assert db_session.query(ImportBatch).count() == 0
