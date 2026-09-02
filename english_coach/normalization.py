"""Deterministic text normalization and deduplication-key construction.

Version 1 deduplication is intentionally simple and embedding-free:
Unicode NFKC normalization, case folding, whitespace collapsing, and
normalization of common smart-quote/dash variants, while always
preserving the original display text for presentation.
"""
from __future__ import annotations

import re
import unicodedata

_SMART_QUOTES = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00ab": '"',
    "\u00bb": '"',
}

_DASHES = {
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
}

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize text for dedup/search keys while remaining human-legible.

    Steps: NFKC normalization, smart quote/dash folding, case folding,
    whitespace collapsing and trimming.
    """
    text = unicodedata.normalize("NFKC", value)
    for source, replacement in _SMART_QUOTES.items():
        text = text.replace(source, replacement)
    for source, replacement in _DASHES.items():
        text = text.replace(source, replacement)
    text = text.casefold()
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_tag(value: str) -> str:
    return normalize_text(value)


def vocabulary_dedup_key(lemma: str, part_of_speech: str, sense_key: str) -> str:
    return "|".join(
        [
            normalize_text(lemma),
            normalize_text(part_of_speech),
            normalize_text(sense_key),
        ]
    )


def expression_dedup_key(expression: str) -> str:
    return normalize_text(expression)


def grammar_dedup_key(pattern_name: str) -> str:
    return normalize_text(pattern_name)


def mistake_dedup_key(wrong_sentence: str, corrected_sentence: str, category: str) -> str:
    return "|".join(
        [
            normalize_text(wrong_sentence),
            normalize_text(corrected_sentence),
            normalize_text(category),
        ]
    )


def dedup_key_for_kind(kind: str, **fields: str) -> str:
    if kind == "vocabulary":
        return vocabulary_dedup_key(fields["lemma"], fields["part_of_speech"], fields["sense_key"])
    if kind == "expression":
        return expression_dedup_key(fields["expression"])
    if kind == "grammar":
        return grammar_dedup_key(fields["pattern_name"])
    if kind == "mistake":
        return mistake_dedup_key(
            fields["wrong_sentence"], fields["corrected_sentence"], fields["category"]
        )
    raise ValueError(f"Unknown kind: {kind}")
