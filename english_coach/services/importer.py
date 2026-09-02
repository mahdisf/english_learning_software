"""Parsing, validation, deduplication, and atomic application of AI session updates."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session as OrmSession

from english_coach import normalization as norm
from english_coach.mastery import QualifyingEvent, compute_mastery, mistake_state
from english_coach.models import (
    ExpressionDetail,
    GrammarDetail,
    ImportBatch,
    ItemExample,
    ItemRevision,
    ItemTag,
    LearningItem,
    MemoryState,
    MistakeDetail,
    Session as SessionModel,
    Tag,
    UsageEvent,
    VocabularyDetail,
    new_uuid,
)
from english_coach.schemas import SessionUpdate
from english_coach.services.deduplication import ReferenceError_, resolve_item

QUALIFYING_EVENT_TYPES = ("user_production", "prompted_recall")


class ImportValidationError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


class ImportConflictError(ValueError):
    pass


class IdempotentImport(Exception):
    """Raised internally to signal a safe no-op re-import."""

    def __init__(self, batch: ImportBatch):
        super().__init__("This update was already imported.")
        self.batch = batch


# ---------------------------------------------------------------------------
# Robust input parsing
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```$", re.DOTALL)


def decode_input_bytes(raw_bytes: bytes) -> str:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportValidationError(f"Input is not valid UTF-8: {exc}") from exc
    return text


def strip_single_code_fence(text: str) -> str:
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1)
    return text


def _reject_constant(value: str):
    raise ValueError(f"Invalid JSON constant encountered: {value}")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"Duplicate object key: '{key}'")
        seen[key] = value
    return seen


def parse_strict_json(text: str) -> dict:
    """Parse JSON while rejecting duplicate keys, NaN/Infinity, and trailing content."""
    decoder = json.JSONDecoder(object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    try:
        obj, end = decoder.raw_decode(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ImportValidationError(f"Invalid JSON: {exc}") from exc
    remainder = text[end:].strip()
    if remainder:
        raise ImportValidationError(
            "Unexpected content after the JSON value (trailing prose, a second JSON "
            "object, or comments are not allowed)."
        )
    if not isinstance(obj, dict):
        raise ImportValidationError("The top-level JSON value must be an object.")
    return obj


def load_session_update(raw_bytes: bytes) -> tuple[SessionUpdate, str, str]:
    """Decode, parse, and validate raw bytes into a SessionUpdate.

    Returns (payload, canonical_text, content_hash).
    """
    text = decode_input_bytes(raw_bytes)
    text = strip_single_code_fence(text)
    obj = parse_strict_json(text)
    try:
        payload = SessionUpdate.model_validate(obj)
    except ValidationError as exc:
        errors = [_format_pydantic_error(e) for e in exc.errors()]
        raise ImportValidationError("Session update failed schema validation.", errors) from exc

    canonical_text = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    content_hash = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return payload, text, content_hash


def _format_pydantic_error(err: dict) -> str:
    loc = ".".join(str(part) for part in err["loc"])
    return f"{loc}: {err['msg']}"


# ---------------------------------------------------------------------------
# Change-set data structures used for preview rendering
# ---------------------------------------------------------------------------


@dataclass
class ScalarChange:
    field: str
    old: object
    new: object


@dataclass
class NewItemChange:
    client_ref: str
    kind: str
    item_id: str
    display_text: str
    importance_score: int
    cefr_level: str | None
    examples: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


@dataclass
class UpdatedItemChange:
    client_ref: str | None
    kind: str
    item_id: str
    display_text: str
    scalar_changes: list[ScalarChange] = field(default_factory=list)
    appended_examples: list[str] = field(default_factory=list)
    appended_topics: list[str] = field(default_factory=list)
    merged_list_changes: list[ScalarChange] = field(default_factory=list)


@dataclass
class MasteryChange:
    item_id: str
    display_text: str
    old_score: int
    new_score: int
    old_status: str
    new_status: str


@dataclass
class UsageEventSummary:
    event_id: str
    event_type: str
    item_id: str
    qualifying: bool


@dataclass
class MemoryChangeSet:
    topics_added: list[str] = field(default_factory=list)
    topics_removed: list[str] = field(default_factory=list)
    goals_added: list[str] = field(default_factory=list)
    goals_removed: list[str] = field(default_factory=list)
    completed_topics_added: list[str] = field(default_factory=list)
    weak_points_upserted: list[str] = field(default_factory=list)
    weak_points_resolved: list[str] = field(default_factory=list)
    next_focus: list[str] = field(default_factory=list)


@dataclass
class ImportChangeSet:
    update_id: str
    session_id: str
    session_is_new: bool
    new_items: list[NewItemChange] = field(default_factory=list)
    updated_items: list[UpdatedItemChange] = field(default_factory=list)
    usage_events: list[UsageEventSummary] = field(default_factory=list)
    mastery_changes: list[MasteryChange] = field(default_factory=list)
    memory_changes: MemoryChangeSet = field(default_factory=MemoryChangeSet)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportExecution:
    changeset: ImportChangeSet | None
    batch: ImportBatch | None
    idempotent: bool
    canonical_text: str = ""


# ---------------------------------------------------------------------------
# Kind-specific helpers
# ---------------------------------------------------------------------------

_DISPLAY_TEXT = {
    "vocabulary": lambda e: e.word,
    "expression": lambda e: e.expression,
    "grammar": lambda e: e.pattern_name,
    "mistake": lambda e: e.wrong_sentence,
}


def _entry_examples(entry) -> list[str]:
    examples = getattr(entry, "examples", None)
    if examples is None:
        examples = getattr(entry, "additional_examples", [])
    return examples


def _dedup_key_for_entry(kind: str, entry) -> str:
    if kind == "vocabulary":
        return norm.vocabulary_dedup_key(entry.lemma, entry.part_of_speech, entry.sense_key)
    if kind == "expression":
        return norm.expression_dedup_key(entry.expression)
    if kind == "grammar":
        return norm.grammar_dedup_key(entry.pattern_name)
    if kind == "mistake":
        return norm.mistake_dedup_key(entry.wrong_sentence, entry.corrected_sentence, entry.category)
    raise ValueError(kind)


def _get_or_create_tag(db: OrmSession, display_tag: str) -> Tag:
    normalized = norm.normalize_tag(display_tag)
    tag = db.query(Tag).filter(Tag.normalized_tag == normalized).one_or_none()
    if tag is None:
        tag = Tag(normalized_tag=normalized, display_tag=display_tag)
        db.add(tag)
        db.flush()
    return tag


def _attach_topics(db: OrmSession, item: LearningItem, topics: list[str]) -> list[str]:
    added = []
    existing_tag_ids = {
        row.tag_id for row in db.query(ItemTag).filter(ItemTag.item_id == item.id).all()
    }
    seen_normalized = set()
    for topic in topics:
        normalized = norm.normalize_tag(topic)
        if normalized in seen_normalized:
            continue
        seen_normalized.add(normalized)
        tag = _get_or_create_tag(db, topic)
        if tag.id not in existing_tag_ids:
            db.add(ItemTag(item_id=item.id, tag_id=tag.id))
            existing_tag_ids.add(tag.id)
            added.append(topic)
    return added


def _add_examples(
    db: OrmSession, item: LearningItem, session_id: str, sentences: list[str]
) -> list[str]:
    added = []
    existing = {
        row.normalized_sentence
        for row in db.query(ItemExample).filter(ItemExample.item_id == item.id).all()
    }
    for sentence in sentences:
        normalized = norm.normalize_text(sentence)
        if not normalized or normalized in existing:
            continue
        existing.add(normalized)
        db.add(
            ItemExample(
                item_id=item.id,
                sentence=sentence,
                source_session_id=session_id,
                normalized_sentence=normalized,
            )
        )
        added.append(sentence)
    return added


def _merge_list(old_list: list[str], new_values: list[str]) -> tuple[list[str], list[str]]:
    """Merge new unique (by normalized text) values into old_list. Returns (merged, appended)."""
    seen = {norm.normalize_text(v) for v in old_list}
    merged = list(old_list)
    appended = []
    for value in new_values:
        normalized = norm.normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(value)
        appended.append(value)
    return merged, appended


def _snapshot_item(item: LearningItem) -> dict:
    detail = (
        item.vocabulary_detail
        or item.expression_detail
        or item.grammar_detail
        or item.mistake_detail
    )
    detail_dict = {}
    if detail is not None:
        for col in detail.__table__.columns:
            if col.name == "item_id":
                continue
            detail_dict[col.name] = getattr(detail, col.name)
    return {
        "kind": item.kind,
        "display_text": item.display_text,
        "cefr_level": item.cefr_level,
        "importance_score": item.importance_score,
        "detail": detail_dict,
    }


# ---------------------------------------------------------------------------
# New-item creation
# ---------------------------------------------------------------------------


def _create_item(
    db: OrmSession, kind: str, entry, session_id: str, dedup_key: str
) -> LearningItem:
    item_id = str(entry.item_id) if entry.item_id else new_uuid()
    display_text = _DISPLAY_TEXT[kind](entry)
    item = LearningItem(
        id=item_id,
        kind=kind,
        dedup_key=dedup_key,
        display_text=display_text,
        cefr_level=entry.cefr_level,
        importance_score=entry.importance_score,
        source_session_id=session_id,
        revision=1,
    )
    db.add(item)
    db.flush()

    if kind == "vocabulary":
        db.add(
            VocabularyDetail(
                item_id=item.id,
                word=entry.word,
                lemma=entry.lemma,
                part_of_speech=entry.part_of_speech,
                sense_key=entry.sense_key,
                meaning_english=entry.meaning_english,
                meaning_persian=entry.meaning_persian,
                ipa_american=entry.ipa_american,
                stress_note=entry.stress_note,
                usage_note=entry.usage_note,
                collocations=list(entry.collocations),
                common_errors=list(entry.common_errors),
            )
        )
    elif kind == "expression":
        db.add(
            ExpressionDetail(
                item_id=item.id,
                expression_text=entry.expression,
                expression_type=entry.expression_type,
                meaning_english=entry.meaning_english,
                meaning_persian=entry.meaning_persian,
                ipa_american=entry.ipa_american,
                usage_contexts=list(entry.usage_contexts),
                common_errors=list(entry.common_errors),
            )
        )
    elif kind == "grammar":
        db.add(
            GrammarDetail(
                item_id=item.id,
                pattern_name=entry.pattern_name,
                explanation_english=entry.explanation_english,
                explanation_persian=entry.explanation_persian,
                structure=entry.structure,
                learner_problem=entry.learner_problem,
                common_errors=list(entry.common_errors),
            )
        )
    elif kind == "mistake":
        db.add(
            MistakeDetail(
                item_id=item.id,
                wrong_sentence=entry.wrong_sentence,
                corrected_sentence=entry.corrected_sentence,
                category=entry.category,
                explanation_english=entry.explanation_english,
                explanation_persian=entry.explanation_persian,
                severity=entry.severity,
                state="active",
                occurrence_count=entry.occurrences_in_session,
            )
        )
    db.flush()
    return item


_SCALAR_FIELDS = {
    "vocabulary": [
        ("meaning_english", "meaning_english"),
        ("meaning_persian", "meaning_persian"),
        ("ipa_american", "ipa_american"),
        ("stress_note", "stress_note"),
        ("usage_note", "usage_note"),
    ],
    "expression": [
        ("meaning_english", "meaning_english"),
        ("meaning_persian", "meaning_persian"),
        ("ipa_american", "ipa_american"),
    ],
    "grammar": [
        ("explanation_english", "explanation_english"),
        ("explanation_persian", "explanation_persian"),
        ("structure", "structure"),
    ],
    "mistake": [
        ("explanation_english", "explanation_english"),
        ("explanation_persian", "explanation_persian"),
    ],
}

_LIST_FIELDS = {
    "vocabulary": ["collocations", "common_errors"],
    "expression": ["usage_contexts", "common_errors"],
    "grammar": ["common_errors"],
    "mistake": [],
}


def _update_item(
    db: OrmSession,
    item: LearningItem,
    kind: str,
    entry,
    session_id: str,
    client_ref: str | None,
) -> UpdatedItemChange:
    before = _snapshot_item(item)
    detail = (
        item.vocabulary_detail
        or item.expression_detail
        or item.grammar_detail
        or item.mistake_detail
    )
    change = UpdatedItemChange(
        client_ref=client_ref, kind=kind, item_id=item.id, display_text=item.display_text
    )

    if item.importance_score != entry.importance_score:
        change.scalar_changes.append(
            ScalarChange("importance_score", item.importance_score, entry.importance_score)
        )
        item.importance_score = entry.importance_score
    if item.cefr_level != entry.cefr_level and entry.cefr_level is not None:
        change.scalar_changes.append(ScalarChange("cefr_level", item.cefr_level, entry.cefr_level))
        item.cefr_level = entry.cefr_level

    for field_name, entry_attr in _SCALAR_FIELDS.get(kind, []):
        new_value = getattr(entry, entry_attr)
        old_value = getattr(detail, field_name)
        if new_value is not None and new_value != old_value:
            change.scalar_changes.append(ScalarChange(field_name, old_value, new_value))
            setattr(detail, field_name, new_value)

    for list_field in _LIST_FIELDS.get(kind, []):
        new_values = getattr(entry, list_field, [])
        old_values = getattr(detail, list_field, [])
        merged, appended = _merge_list(old_values, new_values)
        if appended:
            setattr(detail, list_field, merged)
            change.merged_list_changes.append(ScalarChange(list_field, old_values, merged))

    if kind == "mistake":
        detail.occurrence_count += entry.occurrences_in_session

    appended_examples = _add_examples(db, item, session_id, _entry_examples(entry))
    change.appended_examples = appended_examples

    appended_topics = _attach_topics(db, item, entry.topics)
    change.appended_topics = appended_topics

    item.revision += 1
    db.flush()

    after = _snapshot_item(item)
    db.add(
        ItemRevision(
            item_id=item.id,
            session_id=session_id,
            revision_number=item.revision,
            before_json=before,
            after_json=after,
            change_source="import",
        )
    )
    return change


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def execute_import(
    db: OrmSession, payload: SessionUpdate, canonical_text: str, content_hash: str, filename: str | None
) -> ImportExecution:
    """Apply the update within the current DB transaction (caller commits/rolls back)."""

    existing_by_update_id = (
        db.query(ImportBatch).filter(ImportBatch.update_id == str(payload.update_id)).one_or_none()
    )
    if existing_by_update_id is not None:
        if existing_by_update_id.content_hash == content_hash:
            return ImportExecution(changeset=None, batch=existing_by_update_id, idempotent=True)
        raise ImportConflictError(
            f"update_id {payload.update_id} was already imported with different content."
        )

    existing_by_hash = (
        db.query(ImportBatch).filter(ImportBatch.content_hash == content_hash).one_or_none()
    )
    if existing_by_hash is not None:
        return ImportExecution(changeset=None, batch=existing_by_hash, idempotent=True)

    changeset = ImportChangeSet(
        update_id=str(payload.update_id),
        session_id=str(payload.session.session_id),
        session_is_new=True,
    )

    # --- Session -----------------------------------------------------
    session_id = str(payload.session.session_id)
    existing_session = db.get(SessionModel, session_id)
    if existing_session is not None:
        changeset.session_is_new = False
        changeset.warnings.append(
            f"Session {session_id} already exists; session fields were not modified."
        )
    else:
        local_date = payload.session.ended_at.astimezone(timezone.utc).date().isoformat()
        db.add(
            SessionModel(
                id=session_id,
                started_at=payload.session.started_at,
                ended_at=payload.session.ended_at,
                local_session_date=local_date,
                topic=payload.session.topic,
                session_type=payload.session.session_type,
                summary=payload.session.summary,
                strengths=list(payload.session.strengths),
                weak_points=list(payload.session.weak_points),
                next_focus=list(payload.session.next_focus),
                fluency_notes=list(payload.session.fluency_notes),
            )
        )
        db.flush()

    # --- Items ---------------------------------------------------------
    client_ref_to_item_id: dict[str, str] = {}
    client_ref_kind: dict[str, str] = {}
    seen_new_dedup_keys: dict[tuple[str, str], str] = {}
    affected_item_ids: set[str] = set()

    item_arrays = [
        ("vocabulary", payload.vocabulary),
        ("expression", payload.expressions),
        ("grammar", payload.grammar_patterns),
        ("mistake", payload.mistakes),
    ]

    seen_client_refs: set[str] = set()

    for kind, entries in item_arrays:
        for index, entry in enumerate(entries):
            json_path = f"{kind}[{index}]"
            if entry.client_ref in seen_client_refs:
                raise ImportValidationError(
                    f"{json_path}: duplicate client_ref '{entry.client_ref}' in this file."
                )
            seen_client_refs.add(entry.client_ref)

            dedup_key = _dedup_key_for_entry(kind, entry)
            item_id_str = str(entry.item_id) if entry.item_id else None

            if item_id_str is None:
                dedup_signature = (kind, dedup_key)
                if dedup_signature in seen_new_dedup_keys:
                    other_ref = seen_new_dedup_keys[dedup_signature]
                    raise ImportValidationError(
                        f"{json_path}: '{entry.client_ref}' and '{other_ref}' resolve to the "
                        "same item ambiguously. Provide an existing item_id or a distinct "
                        "sense_key/expression text to disambiguate."
                    )
                seen_new_dedup_keys[dedup_signature] = entry.client_ref

            resolution = resolve_item(
                db, kind=kind, item_id=item_id_str, dedup_key=dedup_key, json_path=json_path
            )

            if resolution.existing_item is not None:
                change = _update_item(
                    db, resolution.existing_item, kind, entry, session_id, entry.client_ref
                )
                changeset.updated_items.append(change)
                item = resolution.existing_item
            else:
                item = _create_item(db, kind, entry, session_id, dedup_key)
                appended_examples = _add_examples(db, item, session_id, _entry_examples(entry))
                appended_topics = _attach_topics(db, item, entry.topics)
                changeset.new_items.append(
                    NewItemChange(
                        client_ref=entry.client_ref,
                        kind=kind,
                        item_id=item.id,
                        display_text=item.display_text,
                        importance_score=item.importance_score,
                        cefr_level=item.cefr_level,
                        examples=appended_examples,
                        topics=appended_topics,
                    )
                )
                db.add(
                    ItemRevision(
                        item_id=item.id,
                        session_id=session_id,
                        revision_number=1,
                        before_json=None,
                        after_json=_snapshot_item(item),
                        change_source="import",
                    )
                )

            client_ref_to_item_id[entry.client_ref] = item.id
            client_ref_kind[entry.client_ref] = kind
            affected_item_ids.add(item.id)

    # --- Usage events ----------------------------------------------------
    seen_event_ids: set[str] = set()
    events_by_item: dict[str, list] = {}

    for index, event in enumerate(payload.usage_events):
        json_path = f"usage_events[{index}]"
        event_id = str(event.event_id)
        if event_id in seen_event_ids:
            raise ImportValidationError(f"{json_path}: duplicate event_id '{event_id}' in this file.")
        seen_event_ids.add(event_id)

        if db.get(UsageEvent, event_id) is not None:
            raise ImportValidationError(f"{json_path}: event_id '{event_id}' already exists.")

        if event.item_id is not None:
            item_id_str = str(event.item_id)
            target_item = db.get(LearningItem, item_id_str)
            if target_item is None:
                raise ReferenceError_(f"{json_path}: item_id {item_id_str} does not exist.")
        else:
            if event.client_ref not in client_ref_to_item_id:
                raise ReferenceError_(
                    f"{json_path}: client_ref '{event.client_ref}' does not resolve to any "
                    "item in this file."
                )
            item_id_str = client_ref_to_item_id[event.client_ref]

        db.add(
            UsageEvent(
                id=event_id,
                item_id=item_id_str,
                session_id=session_id,
                event_type=event.event_type,
                correctness=event.correctness,
                evidence_context=event.evidence_context,
                correction=event.correction,
                occurred_at=event.occurred_at,
            )
        )

        qualifying = event.event_type in QUALIFYING_EVENT_TYPES and event.correctness is not None
        changeset.usage_events.append(
            UsageEventSummary(
                event_id=event_id, event_type=event.event_type, item_id=item_id_str, qualifying=qualifying
            )
        )
        if qualifying:
            events_by_item.setdefault(item_id_str, []).append(event)
        affected_item_ids.add(item_id_str)

    db.flush()

    # --- Recompute mastery for every item touched by a qualifying event ---
    for item_id_str in events_by_item:
        item = db.get(LearningItem, item_id_str)
        assert item is not None, f"item {item_id_str} vanished mid-transaction"
        history = (
            db.query(UsageEvent)
            .filter(
                UsageEvent.item_id == item_id_str,
                UsageEvent.event_type.in_(QUALIFYING_EVENT_TYPES),
                UsageEvent.correctness.is_not(None),
            )
            .order_by(UsageEvent.occurred_at.asc())
            .all()
        )
        qualifying_events = [
            QualifyingEvent(session_id=e.session_id, correct=bool(e.correctness)) for e in history
        ]
        result = compute_mastery(qualifying_events)
        old_score, old_status = item.mastery_score, item.mastery_status
        item.usage_count_total = len(qualifying_events)
        item.usage_count_correct = sum(1 for e in qualifying_events if e.correct)
        if qualifying_events:
            item.last_used_at = history[-1].occurred_at
        item.mastery_score = result.score
        item.mastery_status = result.status
        if old_score != result.score or old_status != result.status:
            changeset.mastery_changes.append(
                MasteryChange(
                    item_id=item.id,
                    display_text=item.display_text,
                    old_score=old_score,
                    new_score=result.score,
                    old_status=old_status,
                    new_status=result.status,
                )
            )

        if item.kind == "mistake" and item.mistake_detail is not None:
            correct_count = sum(1 for e in qualifying_events if e.correct)
            distinct_sessions = len({e.session_id for e in qualifying_events})
            item.mistake_detail.state = mistake_state(correct_count, distinct_sessions)

    # --- Memory patch -----------------------------------------------------
    memory = db.get(MemoryState, 1)
    if memory is None:
        memory = MemoryState(id=1)
        db.add(memory)
        db.flush()

    patch = payload.memory_patch
    memory.current_topics, added = _merge_list(memory.current_topics, patch.current_topics_add)
    changeset.memory_changes.topics_added = added
    removed_norm = {norm.normalize_text(v) for v in patch.current_topics_remove}
    kept = [t for t in memory.current_topics if norm.normalize_text(t) not in removed_norm]
    changeset.memory_changes.topics_removed = [
        t for t in memory.current_topics if norm.normalize_text(t) in removed_norm
    ]
    memory.current_topics = kept

    memory.active_goals, added_goals = _merge_list(memory.active_goals, patch.active_goals_add)
    changeset.memory_changes.goals_added = added_goals
    removed_goals_norm = {norm.normalize_text(v) for v in patch.active_goals_remove}
    changeset.memory_changes.goals_removed = [
        g for g in memory.active_goals if norm.normalize_text(g) in removed_goals_norm
    ]
    memory.active_goals = [
        g for g in memory.active_goals if norm.normalize_text(g) not in removed_goals_norm
    ]

    memory.completed_topics, added_completed = _merge_list(
        memory.completed_topics, patch.completed_topics_add
    )
    changeset.memory_changes.completed_topics_added = added_completed

    weak_points = list(memory.weak_points)
    by_key = {wp["key"]: wp for wp in weak_points}
    for upsert in patch.weak_points_upsert:
        by_key[upsert.key] = {
            "key": upsert.key,
            "description": upsert.description,
            "severity": upsert.severity,
            "evidence": list(upsert.evidence),
            "last_seen_at": upsert.last_seen_at.isoformat(),
        }
        changeset.memory_changes.weak_points_upserted.append(upsert.key)
    for resolved_key in patch.weak_points_resolved:
        if resolved_key in by_key:
            del by_key[resolved_key]
            changeset.memory_changes.weak_points_resolved.append(resolved_key)
    memory.weak_points = list(by_key.values())

    memory.next_session_focus = list(patch.next_session_focus)
    changeset.memory_changes.next_focus = list(patch.next_session_focus)
    memory.last_session_id = session_id

    db.flush()

    # --- Import batch record ----------------------------------------------
    result_summary = {
        "new_items": len(changeset.new_items),
        "updated_items": len(changeset.updated_items),
        "usage_events": len(changeset.usage_events),
        "mastery_changes": len(changeset.mastery_changes),
    }
    batch = ImportBatch(
        update_id=str(payload.update_id),
        schema_version=payload.schema_version,
        original_filename=filename,
        content_hash=content_hash,
        raw_json=canonical_text,
        result_summary=result_summary,
    )
    db.add(batch)
    db.flush()

    return ImportExecution(
        changeset=changeset, batch=batch, idempotent=False, canonical_text=canonical_text
    )
