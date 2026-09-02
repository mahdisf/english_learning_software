"""Anki (.apkg) and TSV export with deterministic GUIDs and pending-item tracking.

No Anki scheduling data (intervals, ease factors, due dates) is ever stored
or generated. This module only produces note content.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import genanki
from sqlalchemy.orm import Session as OrmSession

from english_coach.atomic_io import atomic_write_via
from english_coach.config import Settings
from english_coach.models import AnkiExportBatch, AnkiExportItem, LearningItem

VOCAB_MODEL_ID = 1970010100001
EXPR_MODEL_ID = 1970010100002
GRAMMAR_MODEL_ID = 1970010100003
MISTAKE_MODEL_ID = 1970010100004

VOCAB_DECK_ID = 1970010200001
EXPR_DECK_ID = 1970010200002
GRAMMAR_DECK_ID = 1970010200003
MISTAKE_DECK_ID = 1970010200004

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "anki"


def _read(name: str) -> str:
    return (_TEMPLATE_DIR / name).read_text(encoding="utf-8")


_STYLE = _read("style.css")

VOCAB_FIELDS = [
    "CoachID", "Word", "PartOfSpeech", "TopicCue", "IPA", "MeaningEnglish",
    "MeaningPersian", "Examples", "Collocations", "UsageNote", "CommonErrors",
    "CEFR", "Tags",
]
EXPR_FIELDS = [
    "CoachID", "Expression", "ExpressionType", "MeaningEnglish", "MeaningPersian",
    "IPA", "UsageContexts", "Examples", "CommonErrors", "CEFR", "Tags",
]
GRAMMAR_FIELDS = [
    "CoachID", "PatternName", "Structure", "ExplanationEnglish", "ExplanationPersian",
    "Examples", "LearnerProblem", "CommonErrors", "CEFR", "Tags",
]
MISTAKE_FIELDS = [
    "CoachID", "WrongSentence", "CorrectedSentence", "Category", "Severity",
    "ExplanationEnglish", "ExplanationPersian", "AdditionalExamples",
]


def _model(model_id: int, name: str, fields: list[str], front: str, back: str) -> genanki.Model:
    return genanki.Model(
        model_id,
        name,
        fields=[{"name": f} for f in fields],
        templates=[{"name": "Card 1", "qfmt": front, "afmt": back}],
        css=_STYLE,
    )


VOCAB_MODEL = _model(
    VOCAB_MODEL_ID, "English Coach Vocabulary", VOCAB_FIELDS,
    _read("vocab_front.html"), _read("vocab_back.html"),
)
EXPR_MODEL = _model(
    EXPR_MODEL_ID, "English Coach Expression", EXPR_FIELDS,
    _read("expr_front.html"), _read("expr_back.html"),
)
GRAMMAR_MODEL = _model(
    GRAMMAR_MODEL_ID, "English Coach Grammar", GRAMMAR_FIELDS,
    _read("grammar_front.html"), _read("grammar_back.html"),
)
MISTAKE_MODEL = _model(
    MISTAKE_MODEL_ID, "English Coach Mistake", MISTAKE_FIELDS,
    _read("mistake_front.html"), _read("mistake_back.html"),
)


def _esc(value: str | None) -> str:
    if not value:
        return ""
    return html.escape(value).replace("\n", "<br>")


def _esc_list(values: list[str]) -> str:
    return "<br>".join(_esc(v) for v in values if v)


def item_topics(item: LearningItem, db: OrmSession) -> list[str]:
    from english_coach.models import ItemTag, Tag

    rows = (
        db.query(Tag.display_tag)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .filter(ItemTag.item_id == item.id)
        .all()
    )
    return [r[0] for r in rows]


def item_examples(item: LearningItem, db: OrmSession) -> list[str]:
    from english_coach.models import ItemExample

    rows = (
        db.query(ItemExample.sentence)
        .filter(ItemExample.item_id == item.id)
        .order_by(ItemExample.created_at.asc())
        .all()
    )
    return [r[0] for r in rows]


@dataclass
class RenderedNote:
    kind: str
    deck_name: str
    note: "genanki.Note"
    content_for_hash: dict


def _exportable_content(item: LearningItem, db: OrmSession) -> dict:
    """A JSON-serializable dict capturing everything shown on the card."""
    topics = sorted(item_topics(item, db))
    examples = item_examples(item, db)
    base = {
        "item_id": item.id,
        "kind": item.kind,
        "cefr_level": item.cefr_level,
        "topics": topics,
        "examples": examples,
    }
    if item.kind == "vocabulary":
        d = item.vocabulary_detail
        assert d is not None
        base.update(
            word=d.word, part_of_speech=d.part_of_speech, ipa=d.ipa_american,
            meaning_english=d.meaning_english, meaning_persian=d.meaning_persian,
            collocations=d.collocations, usage_note=d.usage_note, common_errors=d.common_errors,
        )
    elif item.kind == "expression":
        d = item.expression_detail
        assert d is not None
        base.update(
            expression=d.expression_text, expression_type=d.expression_type, ipa=d.ipa_american,
            meaning_english=d.meaning_english, meaning_persian=d.meaning_persian,
            usage_contexts=d.usage_contexts, common_errors=d.common_errors,
        )
    elif item.kind == "grammar":
        d = item.grammar_detail
        assert d is not None
        base.update(
            pattern_name=d.pattern_name, structure=d.structure,
            explanation_english=d.explanation_english, explanation_persian=d.explanation_persian,
            learner_problem=d.learner_problem, common_errors=d.common_errors,
        )
    elif item.kind == "mistake":
        d = item.mistake_detail
        assert d is not None
        base.update(
            wrong_sentence=d.wrong_sentence, corrected_sentence=d.corrected_sentence,
            category=d.category, severity=d.severity,
            explanation_english=d.explanation_english, explanation_persian=d.explanation_persian,
        )
    return base


def content_hash_for_item(item: LearningItem, db: OrmSession) -> str:
    content = _exportable_content(item, db)
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_pending_items(
    db: OrmSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    include_all: bool = False,
    timezone_name: str = "Asia/Tehran",
) -> list[LearningItem]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("--from must not be later than --to")

    tz = ZoneInfo(timezone_name)
    query = db.query(LearningItem).filter(LearningItem.archived_at.is_(None))
    items = query.all()

    result = []
    for item in items:
        if date_from is not None or date_to is not None:
            local_date = item.first_learned_at.astimezone(tz).date()
            if date_from is not None and local_date < date_from:
                continue
            if date_to is not None and local_date > date_to:
                continue

        if include_all:
            result.append(item)
            continue

        latest = (
            db.query(AnkiExportItem)
            .filter(AnkiExportItem.item_id == item.id)
            .order_by(AnkiExportItem.created_at.desc())
            .first()
        )
        current_hash = content_hash_for_item(item, db)
        if latest is None or latest.exported_content_hash != current_hash:
            result.append(item)

    return result


def _render_note(item: LearningItem, db: OrmSession, settings: Settings) -> RenderedNote:
    coach_id = item.id
    topics = item_topics(item, db)
    examples = item_examples(item, db)
    tags_str = " ".join(t.replace(" ", "_") for t in topics)
    cefr = item.cefr_level or ""

    if item.kind == "vocabulary":
        d = item.vocabulary_detail
        assert d is not None
        fields = [
            coach_id, _esc(d.word), _esc(d.part_of_speech), _esc(", ".join(topics)),
            _esc(d.ipa_american), _esc(d.meaning_english), _esc(d.meaning_persian),
            _esc_list(examples), _esc_list(d.collocations), _esc(d.usage_note),
            _esc_list(d.common_errors), _esc(cefr), _esc(tags_str),
        ]
        note = genanki.Note(
            model=VOCAB_MODEL, fields=fields, guid=genanki.guid_for(item.id),
            tags=[t.replace(" ", "_") for t in topics],
        )
        return RenderedNote(item.kind, settings.anki.vocabulary_deck, note, {})
    if item.kind == "expression":
        d = item.expression_detail
        assert d is not None
        fields = [
            coach_id, _esc(d.expression_text), _esc(d.expression_type), _esc(d.meaning_english),
            _esc(d.meaning_persian), _esc(d.ipa_american), _esc_list(d.usage_contexts),
            _esc_list(examples), _esc_list(d.common_errors), _esc(cefr), _esc(tags_str),
        ]
        note = genanki.Note(
            model=EXPR_MODEL, fields=fields, guid=genanki.guid_for(item.id),
            tags=[t.replace(" ", "_") for t in topics],
        )
        return RenderedNote(item.kind, settings.anki.expressions_deck, note, {})
    if item.kind == "grammar":
        d = item.grammar_detail
        assert d is not None
        fields = [
            coach_id, _esc(d.pattern_name), _esc(d.structure), _esc(d.explanation_english),
            _esc(d.explanation_persian), _esc_list(examples), _esc(d.learner_problem),
            _esc_list(d.common_errors), _esc(cefr), _esc(tags_str),
        ]
        note = genanki.Note(
            model=GRAMMAR_MODEL, fields=fields, guid=genanki.guid_for(item.id),
            tags=[t.replace(" ", "_") for t in topics],
        )
        return RenderedNote(item.kind, settings.anki.grammar_deck, note, {})
    if item.kind == "mistake":
        d = item.mistake_detail
        assert d is not None
        fields = [
            coach_id, _esc(d.wrong_sentence), _esc(d.corrected_sentence), _esc(d.category),
            _esc(d.severity), _esc(d.explanation_english), _esc(d.explanation_persian),
            _esc_list(examples),
        ]
        note = genanki.Note(
            model=MISTAKE_MODEL, fields=fields, guid=genanki.guid_for(item.id),
        )
        return RenderedNote(item.kind, settings.anki.mistakes_deck, note, {})
    raise ValueError(f"Unknown kind: {item.kind}")


@dataclass
class AnkiExportResult:
    written: bool
    file_path: Path | None
    item_count: int
    batch_id: str | None
    message: str


def export_apkg(
    db: OrmSession,
    settings: Settings,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    include_all: bool = False,
    output_path: Path | None = None,
) -> AnkiExportResult:
    items = get_pending_items(
        db, date_from=date_from, date_to=date_to, include_all=include_all,
        timezone_name=settings.general.timezone,
    )
    if not items:
        return AnkiExportResult(False, None, 0, None, "No pending items matched the given filters.")

    decks = {
        settings.anki.vocabulary_deck: genanki.Deck(VOCAB_DECK_ID, settings.anki.vocabulary_deck),
        settings.anki.expressions_deck: genanki.Deck(EXPR_DECK_ID, settings.anki.expressions_deck),
        settings.anki.grammar_deck: genanki.Deck(GRAMMAR_DECK_ID, settings.anki.grammar_deck),
        settings.anki.mistakes_deck: genanki.Deck(MISTAKE_DECK_ID, settings.anki.mistakes_deck),
    }

    rendered_hashes: dict[str, str] = {}
    for item in items:
        rendered = _render_note(item, db, settings)
        decks[rendered.deck_name].add_note(rendered.note)
        rendered_hashes[item.id] = content_hash_for_item(item, db)

    package = genanki.Package(list(decks.values()))

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = settings.exports_dir / f"anki_export_{timestamp}.apkg"

    atomic_write_via(output_path, package.write_to_file)

    content_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()

    batch = AnkiExportBatch(
        filename=output_path.name,
        format="apkg",
        filter_from=date_from.isoformat() if date_from else None,
        filter_to=date_to.isoformat() if date_to else None,
        include_all=include_all,
        content_hash=content_hash,
        item_count=len(items),
    )
    db.add(batch)
    db.flush()
    for item in items:
        db.add(
            AnkiExportItem(
                export_batch_id=batch.id,
                item_id=item.id,
                item_revision=item.revision,
                exported_content_hash=rendered_hashes[item.id],
            )
        )
    db.commit()

    return AnkiExportResult(
        True, output_path, len(items), batch.id,
        f"Wrote {len(items)} note(s) to {output_path}",
    )


_TSV_COLUMNS = {
    "vocabulary": VOCAB_FIELDS,
    "expression": EXPR_FIELDS,
    "grammar": GRAMMAR_FIELDS,
    "mistake": MISTAKE_FIELDS,
}


def export_tsv(
    db: OrmSession,
    settings: Settings,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    include_all: bool = False,
    output_dir: Path | None = None,
) -> AnkiExportResult:
    items = get_pending_items(
        db, date_from=date_from, date_to=date_to, include_all=include_all,
        timezone_name=settings.general.timezone,
    )
    if not items:
        return AnkiExportResult(False, None, 0, None, "No pending items matched the given filters.")

    output_dir = output_dir or settings.exports_dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    by_kind: dict[str, list[LearningItem]] = {"vocabulary": [], "expression": [], "grammar": [], "mistake": []}
    for item in items:
        by_kind[item.kind].append(item)

    deck_names = {
        "vocabulary": settings.anki.vocabulary_deck,
        "expression": settings.anki.expressions_deck,
        "grammar": settings.anki.grammar_deck,
        "mistake": settings.anki.mistakes_deck,
    }
    model_names = {
        "vocabulary": "English Coach Vocabulary",
        "expression": "English Coach Expression",
        "grammar": "English Coach Grammar",
        "mistake": "English Coach Mistake",
    }

    written_files: list[Path] = []
    rendered_hashes: dict[str, str] = {}

    for kind, kind_items in by_kind.items():
        if not kind_items:
            continue
        columns = _TSV_COLUMNS[kind]
        buf = io.StringIO()
        buf.write("#separator:tab\n")
        buf.write("#html:true\n")
        buf.write(f"#notetype:{model_names[kind]}\n")
        buf.write(f"#deck:{deck_names[kind]}\n")
        buf.write(f"#columns:{chr(9).join(columns)}\n")
        writer = csv.writer(buf, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        for item in kind_items:
            rendered = _render_note(item, db, settings)
            writer.writerow(rendered.note.fields)
            rendered_hashes[item.id] = content_hash_for_item(item, db)
        file_path = output_dir / f"anki_export_{kind}_{timestamp}.tsv"
        atomic_write_via(file_path, _make_text_writer(buf.getvalue()))
        written_files.append(file_path)

    instructions = _tsv_instructions(written_files)
    instructions_path = output_dir / f"anki_export_{timestamp}_import_instructions.md"
    atomic_write_via(instructions_path, _make_text_writer(instructions))

    all_bytes = b"".join(f.read_bytes() for f in written_files)
    content_hash = hashlib.sha256(all_bytes).hexdigest()

    batch = AnkiExportBatch(
        filename=", ".join(f.name for f in written_files),
        format="tsv",
        filter_from=date_from.isoformat() if date_from else None,
        filter_to=date_to.isoformat() if date_to else None,
        include_all=include_all,
        content_hash=content_hash,
        item_count=len(items),
    )
    db.add(batch)
    db.flush()
    for item in items:
        db.add(
            AnkiExportItem(
                export_batch_id=batch.id,
                item_id=item.id,
                item_revision=item.revision,
                exported_content_hash=rendered_hashes[item.id],
            )
        )
    db.commit()

    return AnkiExportResult(
        True, written_files[0] if written_files else None, len(items), batch.id,
        f"Wrote {len(items)} note(s) across {len(written_files)} TSV file(s) to {output_dir}",
    )


def _make_text_writer(data: str):
    def _write(path_str: str) -> None:
        Path(path_str).write_text(data, encoding="utf-8")

    return _write


def _tsv_instructions(files: list[Path]) -> str:
    lines = ["# Anki TSV import instructions", ""]
    lines.append("In Anki desktop, use *File -> Import* and select each file below.")
    lines.append("Anki reads the `#notetype:`, `#deck:`, and `#columns:` header lines automatically.")
    lines.append("")
    for f in files:
        lines.append(f"- `{f.name}`")
    lines.append("")
    lines.append(
        "The first ordinary column, `CoachID`, holds this application's stable item UUID. "
        "Do not map it to an Anki field used for study; it exists so future re-imports "
        "can be matched reliably if you ever need to reconcile manually."
    )
    return "\n".join(lines)
