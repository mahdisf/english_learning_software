"""Duplicate resolution helpers shared by the importer.

Resolution order per item, as specified:
1. A supplied ``item_id`` wins over text matching, provided the existing
   item has the matching ``kind``. A type mismatch is a hard rejection.
2. Otherwise, the normalized dedup key is looked up. An unambiguous single
   match proposes an update; no match proposes a new item.
3. Ambiguity inside the *same file* (two new items normalizing to the same
   key) is rejected with an actionable message.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session as OrmSession

from english_coach.models import LearningItem


class ReferenceError_(ValueError):
    """Raised for unresolvable or conflicting references."""


@dataclass
class ResolutionResult:
    existing_item: LearningItem | None
    is_update: bool


def resolve_item(
    db: OrmSession,
    *,
    kind: str,
    item_id: str | None,
    dedup_key: str,
    json_path: str,
) -> ResolutionResult:
    if item_id is not None:
        existing = db.get(LearningItem, item_id)
        if existing is None:
            raise ReferenceError_(
                f"{json_path}: item_id {item_id} does not exist in the knowledge base"
            )
        if existing.kind != kind:
            raise ReferenceError_(
                f"{json_path}: item_id {item_id} has kind '{existing.kind}', "
                f"expected '{kind}'"
            )
        return ResolutionResult(existing_item=existing, is_update=True)

    existing = (
        db.query(LearningItem)
        .filter(LearningItem.kind == kind, LearningItem.dedup_key == dedup_key)
        .one_or_none()
    )
    if existing is not None:
        return ResolutionResult(existing_item=existing, is_update=True)
    return ResolutionResult(existing_item=None, is_update=False)
