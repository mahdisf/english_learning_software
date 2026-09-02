import zipfile
from datetime import date
from pathlib import Path

import genanki
import pytest

from english_coach.services import anki_exporter
from english_coach.services.importer import execute_import, load_session_update
from english_coach.models import LearningItem

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = REPO_ROOT / "examples" / "session_update.example.json"


def _import_example(db_session):
    raw = EXAMPLE_PATH.read_bytes()
    payload, canonical_text, content_hash = load_session_update(raw)
    execution = execute_import(db_session, payload, canonical_text, content_hash, "example.json")
    db_session.commit()
    return execution


def test_all_items_are_pending_before_first_export(db_session, db_settings):
    _import_example(db_session)
    pending = anki_exporter.get_pending_items(db_session, timezone_name=db_settings.general.timezone)
    assert len(pending) == 5


def test_apkg_export_marks_items_no_longer_pending(db_session, db_settings):
    _import_example(db_session)
    result = anki_exporter.export_apkg(db_session, db_settings)
    assert result.written
    assert result.item_count == 5
    assert result.file_path.is_file()
    assert result.file_path.stat().st_size > 0

    pending_after = anki_exporter.get_pending_items(db_session, timezone_name=db_settings.general.timezone)
    assert pending_after == []


def test_changed_item_becomes_pending_again(db_session, db_settings):
    _import_example(db_session)
    anki_exporter.export_apkg(db_session, db_settings)

    item = db_session.query(LearningItem).filter(LearningItem.kind == "vocabulary").first()
    item.vocabulary_detail.usage_note = "A materially different usage note."
    db_session.commit()

    pending_after_edit = anki_exporter.get_pending_items(db_session, timezone_name=db_settings.general.timezone)
    assert item.id in {i.id for i in pending_after_edit}


def test_export_all_includes_already_exported_items(db_session, db_settings):
    _import_example(db_session)
    anki_exporter.export_apkg(db_session, db_settings)
    result = anki_exporter.export_apkg(db_session, db_settings, include_all=True)
    assert result.written
    assert result.item_count == 5


def test_empty_export_does_not_write_file_or_record(db_session, db_settings):
    _import_example(db_session)
    anki_exporter.export_apkg(db_session, db_settings)
    # Everything already exported and nothing changed -> nothing pending.
    from english_coach.models import AnkiExportBatch

    batches_before = db_session.query(AnkiExportBatch).count()
    result = anki_exporter.export_apkg(db_session, db_settings)
    assert result.written is False
    assert "No pending items" in result.message
    batches_after = db_session.query(AnkiExportBatch).count()
    assert batches_before == batches_after


def test_invalid_date_range_rejected(db_session, db_settings):
    with pytest.raises(ValueError):
        anki_exporter.export_apkg(
            db_session, db_settings, date_from=date(2026, 6, 1), date_to=date(2026, 1, 1)
        )


def test_inclusive_date_range_filtering(db_session, db_settings):
    _import_example(db_session)
    far_future = date(2099, 1, 1)
    result = anki_exporter.export_apkg(db_session, db_settings, date_from=far_future)
    assert result.written is False


def test_deterministic_guid_for_same_item(db_session):
    item_id = "3b1f7f0a-1111-4a11-9a11-000000000099"
    guid1 = genanki.guid_for(item_id)
    guid2 = genanki.guid_for(item_id)
    assert guid1 == guid2


def test_apkg_package_contains_expected_note_count(db_session, db_settings):
    _import_example(db_session)
    result = anki_exporter.export_apkg(db_session, db_settings)
    with zipfile.ZipFile(result.file_path) as zf:
        names = zf.namelist()
        assert "collection.anki21" in names or "collection.anki2" in names


def test_tsv_export_utf8_and_escaping(db_session, db_settings):
    from english_coach.models import VocabularyDetail

    _import_example(db_session)
    vocab_detail = db_session.query(VocabularyDetail).first()
    vocab_detail.meaning_persian = "این یک آزمایش است"
    vocab_detail.usage_note = 'Contains a "quote", a\ttab, and a\nnewline.'
    db_session.commit()

    result = anki_exporter.export_tsv(db_session, db_settings)
    assert result.written
    vocab_files = list(db_settings.exports_dir.glob("anki_export_vocabulary_*.tsv"))
    assert vocab_files
    content = vocab_files[0].read_text(encoding="utf-8")
    assert "#separator:tab" in content
    assert "#html:true" in content
    assert "این یک آزمایش است" in content

    instructions = list(db_settings.exports_dir.glob("*_import_instructions.md"))
    assert instructions


def test_tsv_export_empty_when_nothing_pending(db_session, db_settings):
    result = anki_exporter.export_tsv(db_session, db_settings)
    assert result.written is False
