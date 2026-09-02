"""A simple, safe indexed LIKE-based search across learning items."""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session as OrmSession

from english_coach.models import (
    ExpressionDetail,
    GrammarDetail,
    ItemExample,
    ItemTag,
    LearningItem,
    MistakeDetail,
    Tag,
    VocabularyDetail,
)


def search_items(db: OrmSession, query: str, limit: int = 50) -> list[LearningItem]:
    pattern = f"%{query}%"

    ids: set[str] = set()

    ids.update(
        row.id
        for row in db.query(LearningItem.id)
        .filter(LearningItem.display_text.ilike(pattern))
        .all()
    )
    ids.update(
        row.item_id
        for row in db.query(VocabularyDetail.item_id)
        .filter(
            or_(
                VocabularyDetail.meaning_english.ilike(pattern),
                VocabularyDetail.meaning_persian.ilike(pattern),
                VocabularyDetail.usage_note.ilike(pattern),
            )
        )
        .all()
    )
    ids.update(
        row.item_id
        for row in db.query(ExpressionDetail.item_id)
        .filter(
            or_(
                ExpressionDetail.meaning_english.ilike(pattern),
                ExpressionDetail.meaning_persian.ilike(pattern),
            )
        )
        .all()
    )
    ids.update(
        row.item_id
        for row in db.query(GrammarDetail.item_id)
        .filter(
            or_(
                GrammarDetail.explanation_english.ilike(pattern),
                GrammarDetail.explanation_persian.ilike(pattern),
                GrammarDetail.structure.ilike(pattern),
            )
        )
        .all()
    )
    ids.update(
        row.item_id
        for row in db.query(MistakeDetail.item_id)
        .filter(
            or_(
                MistakeDetail.wrong_sentence.ilike(pattern),
                MistakeDetail.corrected_sentence.ilike(pattern),
                MistakeDetail.explanation_english.ilike(pattern),
            )
        )
        .all()
    )
    ids.update(
        row.item_id
        for row in db.query(ItemExample.item_id).filter(ItemExample.sentence.ilike(pattern)).all()
    )
    ids.update(
        row.item_id
        for row in db.query(ItemTag.item_id)
        .join(Tag, Tag.id == ItemTag.tag_id)
        .filter(Tag.display_tag.ilike(pattern))
        .all()
    )

    if not ids:
        return []

    items = db.query(LearningItem).filter(LearningItem.id.in_(ids)).limit(limit).all()
    return items
