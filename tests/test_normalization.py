from english_coach.normalization import (
    expression_dedup_key,
    grammar_dedup_key,
    mistake_dedup_key,
    normalize_text,
    vocabulary_dedup_key,
)


def test_normalize_text_case_and_whitespace():
    assert normalize_text("  Mitigate   Risk  ") == "mitigate risk"


def test_normalize_text_smart_quotes_and_dashes():
    assert normalize_text("don\u2019t \u2014 stop") == "don't - stop"


def test_normalize_text_nfkc():
    # Fullwidth characters normalize to their ASCII equivalents under NFKC.
    assert normalize_text("\uff41\uff42\uff43") == "abc"


def test_vocabulary_dedup_key_same_sense_matches():
    key1 = vocabulary_dedup_key("Mitigate", "Verb", "reduce-harm-or-risk")
    key2 = vocabulary_dedup_key("mitigate", "verb", "Reduce-Harm-Or-Risk")
    assert key1 == key2


def test_vocabulary_dedup_key_different_senses_do_not_match():
    key1 = vocabulary_dedup_key("light", "noun", "illumination")
    key2 = vocabulary_dedup_key("light", "adjective", "not-heavy")
    assert key1 != key2


def test_expression_dedup_key_normalizes():
    assert expression_dedup_key("Feel Singled Out") == expression_dedup_key("feel   singled out")


def test_grammar_dedup_key_normalizes():
    assert grammar_dedup_key("Present Perfect") == grammar_dedup_key("present perfect")


def test_mistake_dedup_key_requires_all_three_fields_to_match():
    a = mistake_dedup_key("I made an example.", "I gave an example.", "word_choice")
    b = mistake_dedup_key("I made an example.", "I gave an example.", "grammar")
    assert a != b
