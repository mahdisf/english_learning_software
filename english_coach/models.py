"""SQLAlchemy ORM models for the English Coach knowledge base."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


ITEM_KINDS = ("vocabulary", "expression", "grammar", "mistake")
OBSERVED_FROM = ("user", "coach", "both")
EVENT_TYPES = (
    "user_production",
    "prompted_recall",
    "coach_introduction",
    "mistake_occurrence",
)
MASTERY_STATUSES = ("new", "learning", "practicing", "strong", "mastered")
MISTAKE_STATES = ("active", "improving", "resolved")
SEVERITIES = ("low", "medium", "high")


class LearnerProfile(Base):
    __tablename__ = "learner_profile"
    __table_args__ = (CheckConstraint("id = 1", name="ck_learner_profile_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    native_language: Mapped[str] = mapped_column(String(64), nullable=False)
    current_level: Mapped[str] = mapped_column(String(8), nullable=False)
    target_level: Mapped[str] = mapped_column(String(8), nullable=False)
    english_variety: Mapped[str] = mapped_column(String(64), nullable=False)
    pronunciation_standard: Mapped[str] = mapped_column(String(64), nullable=False)
    daily_study_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    persian_meaning_policy: Mapped[str] = mapped_column(Text, nullable=False)
    professional_background: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    learning_goals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    default_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    update_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    local_session_date: Mapped[str] = mapped_column(String(10), nullable=False)
    topic: Mapped[str] = mapped_column(String(256), nullable=False)
    session_type: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weak_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    next_focus: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fluency_notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_import_batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("import_batches.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LearningItem(Base):
    __tablename__ = "learning_items"
    __table_args__ = (
        UniqueConstraint("kind", "dedup_key", name="uq_learning_items_kind_dedup_key"),
        CheckConstraint(
            "kind in ('vocabulary','expression','grammar','mistake')",
            name="ck_learning_items_kind",
        ),
        CheckConstraint(
            "importance_score >= 1 AND importance_score <= 10",
            name="ck_learning_items_importance",
        ),
        CheckConstraint(
            "mastery_score >= 0 AND mastery_score <= 100", name="ck_learning_items_mastery"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(512), nullable=False)
    display_text: Mapped[str] = mapped_column(String(512), nullable=False)
    cefr_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    importance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    mastery_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mastery_status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    manual_mastery_override: Mapped[str | None] = mapped_column(String(16), nullable=True)
    usage_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_count_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_learned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vocabulary_detail: Mapped["VocabularyDetail | None"] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan"
    )
    expression_detail: Mapped["ExpressionDetail | None"] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan"
    )
    grammar_detail: Mapped["GrammarDetail | None"] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan"
    )
    mistake_detail: Mapped["MistakeDetail | None"] = relationship(
        back_populates="item", uselist=False, cascade="all, delete-orphan"
    )
    examples: Mapped[list["ItemExample"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class VocabularyDetail(Base):
    __tablename__ = "vocabulary_details"

    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learning_items.id"), primary_key=True
    )
    word: Mapped[str] = mapped_column(String(256), nullable=False)
    lemma: Mapped[str] = mapped_column(String(256), nullable=False)
    part_of_speech: Mapped[str] = mapped_column(String(32), nullable=False)
    sense_key: Mapped[str] = mapped_column(String(128), nullable=False)
    meaning_english: Mapped[str] = mapped_column(Text, nullable=False)
    meaning_persian: Mapped[str | None] = mapped_column(Text, nullable=True)
    ipa_american: Mapped[str | None] = mapped_column(String(256), nullable=True)
    stress_note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    usage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    collocations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    common_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    item: Mapped[LearningItem] = relationship(back_populates="vocabulary_detail")


class ExpressionDetail(Base):
    __tablename__ = "expression_details"

    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learning_items.id"), primary_key=True
    )
    expression_text: Mapped[str] = mapped_column(String(512), nullable=False)
    expression_type: Mapped[str] = mapped_column(String(32), nullable=False)
    meaning_english: Mapped[str] = mapped_column(Text, nullable=False)
    meaning_persian: Mapped[str | None] = mapped_column(Text, nullable=True)
    ipa_american: Mapped[str | None] = mapped_column(String(256), nullable=True)
    usage_contexts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    common_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    item: Mapped[LearningItem] = relationship(back_populates="expression_detail")


class GrammarDetail(Base):
    __tablename__ = "grammar_details"

    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learning_items.id"), primary_key=True
    )
    pattern_name: Mapped[str] = mapped_column(String(256), nullable=False)
    explanation_english: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_persian: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure: Mapped[str] = mapped_column(Text, nullable=False)
    learner_problem: Mapped[str] = mapped_column(Text, nullable=False)
    common_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    item: Mapped[LearningItem] = relationship(back_populates="grammar_detail")


class MistakeDetail(Base):
    __tablename__ = "mistake_details"

    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learning_items.id"), primary_key=True
    )
    wrong_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation_english: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_persian: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    item: Mapped[LearningItem] = relationship(back_populates="mistake_detail")


class ItemExample(Base):
    __tablename__ = "item_examples"
    __table_args__ = (
        UniqueConstraint("item_id", "normalized_sentence", name="uq_item_examples_norm"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("learning_items.id"))
    sentence: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=True
    )
    normalized_sentence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[LearningItem] = relationship(back_populates="examples")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    normalized_tag: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_tag: Mapped[str] = mapped_column(String(128), nullable=False)


class ItemTag(Base):
    __tablename__ = "item_tags"

    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("learning_items.id"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), primary_key=True)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(
            "event_type in ('user_production','prompted_recall',"
            "'coach_introduction','mistake_occurrence')",
            name="ck_usage_events_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("learning_items.id"))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    correctness: Mapped[bool | None] = mapped_column(nullable=True)
    evidence_context: Mapped[str] = mapped_column(Text, nullable=False)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    import_batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("import_batches.id"), nullable=True
    )


class MemoryState(Base):
    __tablename__ = "memory_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_memory_state_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    current_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    active_goals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weak_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    completed_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    next_session_focus: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ItemRevision(Base):
    __tablename__ = "item_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("learning_items.id"))
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    change_source: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnkiExportBatch(Base):
    __tablename__ = "anki_export_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    filter_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    filter_to: Mapped[str | None] = mapped_column(String(10), nullable=True)
    include_all: Mapped[bool] = mapped_column(default=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnkiExportItem(Base):
    __tablename__ = "anki_export_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    export_batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("anki_export_batches.id")
    )
    item_id: Mapped[str] = mapped_column(String(36), ForeignKey("learning_items.id"))
    item_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    exported_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
