import json
import re
from pathlib import Path

from english_coach.schemas import SessionUpdate

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "english_coach_system_prompt.md"

_JSON_BLOCK_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def _json_blocks() -> list[dict]:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    blocks = []
    for match in _JSON_BLOCK_RE.finditer(text):
        blocks.append(json.loads(match.group(1)))
    return blocks


def test_prompt_json_blocks_are_valid_json():
    blocks = _json_blocks()
    assert len(blocks) >= 5


def test_prompt_root_structure_matches_schema_fields():
    blocks = _json_blocks()
    root_candidates = [b for b in blocks if isinstance(b, dict) and "schema_version" in b]
    assert root_candidates, "Expected the prompt to include the root session-update JSON shape."
    root = root_candidates[0]
    assert set(root.keys()) == set(SessionUpdate.model_fields.keys())


def test_prompt_vocabulary_example_matches_schema():
    blocks = _json_blocks()
    vocab_candidates = [b for b in blocks if isinstance(b, dict) and "lemma" in b]
    assert vocab_candidates
    from english_coach.schemas import VocabularyItem

    sample = dict(vocab_candidates[0])
    sample["item_id"] = None
    VocabularyItem.model_validate(sample)
