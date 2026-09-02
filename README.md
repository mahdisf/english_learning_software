# English Coach — Local AI-Powered Personal English Coaching Knowledge System

[![Tests](https://github.com/mahdisf/english_learning_software/actions/workflows/tests.yml/badge.svg)](https://github.com/mahdisf/english_learning_software/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.12+-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/mahdisf/english_learning_software/releases)

> **Stable — v1.0.0 released.** Local-first, no network calls, no AI key required to try.

A **local-first**, SQLite-backed knowledge base that tracks your English vocabulary,
expressions, grammar patterns, mistakes, and coaching memory over time. You talk to
an external AI (e.g. ChatGPT) using the included system prompt, the AI produces a
structured JSON "session update," and this application lets you **preview every
change before it touches your database**, then exports polished Anki/AnkiDroid
flashcards and a compact context file for your next AI session.

## Privacy boundary

- This application makes **no network calls** and stores everything in a local
  SQLite file. It never talks to OpenAI, Anki, or any other service.
- It does **not** store full conversation transcripts — only summaries, selected
  learning items, mistakes, usage evidence snippets, and coaching memory.
- **Local storage does not make your AI conversation private.** Whatever you paste
  into ChatGPT (or any other external AI) is subject to that service's own privacy
  policy and terms. This tool only protects what happens *after* you bring the
  session-update JSON back to your own machine.

## What it does

1. Exports a compact JSON/Markdown **AI context** from your knowledge base.
2. You paste the system prompt (`prompts/english_coach_system_prompt.md`) and,
   optionally, the AI context JSON into a chat with an external AI and have a
   30-minute English session.
3. At the end, you type `/export` and the AI returns one JSON object (the
   **session update**).
4. You save that JSON to a file and run `english-coach import`, which validates it,
   shows a detailed preview of every proposed change, and only touches the database
   after you approve.
5. The app then exports Anki/AnkiDroid flashcards (`.apkg`) and a Markdown session
   report.

The app **never reproduces Anki's scheduling algorithm** — it stores no intervals,
ease factors, or due dates. Anki/AnkiDroid remains solely responsible for spaced
repetition; this app is only a knowledge and coaching-memory layer.

## Installation

Requires Python 3.12+.

### Windows (PowerShell or Git Bash)

```sh
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

### macOS / Linux

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs both the `english-coach` console command and makes
`python -m english_coach` work.

## First-time setup

```sh
english-coach init
```

This creates `data/`, `exports/`, and `reports/` directories, applies all Alembic
migrations, and seeds the learner-profile and memory-state singleton rows. It is
**safe to run repeatedly** — it will not duplicate seed data, and it takes an
automatic backup before migrating an existing non-empty database.

The SQLite database lives at `data/english_coach.db` by default (configurable —
see below).

## Quick verify (no AI required)

Run the entire pipeline against a bundled example to confirm everything works:

```sh
english-coach init
english-coach validate examples/session_update.example.json
english-coach import examples/session_update.example.json --yes
english-coach report progress
english-coach search "mitigate"
```

The `examples/` directory ships with a complete sample session update containing
one item of each kind (vocabulary, expression, grammar, mistake), usage events,
and a memory patch. `validate` shows a detailed preview of every change **without
touching the database** — you can inspect it before running `import`.

Expected `progress` output after importing:

```text
# Progress report
Total sessions recorded: 1
## Counts by kind and mastery status
| Kind        | Status      | Count |
|---|---|---|
| vocabulary  | new         | 1     |
| vocabulary  | practicing  | 1     |
| expression  | new         | 1     |
| grammar     | practicing  | 1     |
| mistake     | new         | 1     |

## Strongest areas
- [vocabulary] delegate (mastery 57)
- [grammar] Present perfect for an unfinished result (mastery 57)
...

## Recommended focus
- Practice mitigate/mitigation in risk-reporting contexts
- Continue article usage before role nouns
```

## Configuration

Copy `config.example.toml` to `config.toml` (git-ignored) to customize paths, the
default timezone (`Asia/Tehran` by default), deck names, the AI-context item
budget, or the learner profile. If `config.toml` is absent, sensible defaults
matching `config.example.toml` are used automatically. You can also point at a
config file explicitly with the `ENGLISH_COACH_CONFIG` environment variable.

## The full manual workflow

### 1. Export context for the AI

```sh
english-coach export ai-context
```

Writes `exports/ai_context_<timestamp>.json` and `.md`. The JSON is what you upload
to the AI; the Markdown is for your own inspection. Use `--full` to include every
non-archived item instead of the compact, prioritized default (useful for a full
review, but potentially large).

### 2. Have your session

Start a new chat with your AI of choice. Paste in the contents of
`prompts/english_coach_system_prompt.md`, then (optionally) upload/paste the
`ai_context_*.json` file. Have your 30-minute English conversation.

### 3. Export the session update

When you are done, type `/export` in the chat. The AI returns exactly one JSON
object — no prose, no code fence. Save it to a file, e.g. `session_update.json`.

### 4. Validate (optional, no database changes)

```sh
english-coach validate session_update.json
```

Parses the file, checks it against the strict schema, resolves every item/usage
reference, and shows the exact preview `import` would show — without writing
anything to the database.

### 5. Import

```sh
english-coach import session_update.json
```

This shows the same detailed preview (new items, matched/updated items with old →
new values, appended examples/tags, usage events, mastery/counter changes, memory
changes, and warnings) and asks:

```text
Apply all displayed changes? [y/N]
```

Only an explicit "y" applies anything. Everything is applied in **one atomic
transaction** — if anything fails, nothing is written. After a successful import,
the approved JSON is copied into `data/imported/`, an import-batch record is
stored, and a Markdown session report is written to `reports/`.

Use `--yes` to skip the interactive prompt (the preview is still printed first).
This is intended for trusted automation/tests — **it will apply changes without a
human pressing "y", so use it only when you already trust the input file.**

Re-importing the exact same file is a safe no-op (it is recognized by its
`update_id` and content hash and reported as "already imported"). Reusing an
`update_id` with different content is rejected as a conflict.

### 6. Reports and search

```sh
english-coach report latest       # the most recent session report
english-coach report session <SESSION_ID>
english-coach report progress     # counts, mastery, active mistakes, focus areas
english-coach search "mitigate"
english-coach item show <ITEM_ID>
```

### 7. Export Anki/AnkiDroid flashcards

```sh
english-coach export anki
```

- Default format is a single `.apkg` file (via `genanki`) with four subdecks:
  `English Coach::Vocabulary`, `::Expressions`, `::Grammar`, `::Mistakes`.
- By default, every **pending** item is exported: an item is pending if it has
  never been successfully exported, or if its content changed since its last
  export. Editing an item (via a later import) makes it pending again automatically.
- `--all` exports every matching non-archived item, even if unchanged since its
  last export.
- `--from YYYY-MM-DD` / `--to YYYY-MM-DD` are optional, independent, **inclusive**
  filters on the item's local `first_learned` date (either or both may be given;
  `--from` later than `--to` is rejected).
- `--format tsv` writes a UTF-8 TSV fallback (one file per note type, with Anki
  import header comments) plus a short `..._import_instructions.md` file, instead
  of an `.apkg`.
- If nothing matches, the app clearly reports that and does **not** create an
  empty file or export record.
- No Anki scheduling data (intervals, ease factors, due dates) is ever stored or
  exported — only note content.

**Importing into Anki/AnkiDroid:** open Anki desktop, *File → Import*, choose the
generated `.apkg` (or, for the TSV fallback, *File → Import* each `.tsv` — Anki
reads the embedded `#notetype:`/`#deck:`/`#columns:` header lines automatically).
Copy the resulting collection to your phone via AnkiDroid's normal sync. Notes use
deterministic GUIDs derived from each item's stable UUID, so re-exporting and
re-importing **updates** existing notes instead of duplicating them.

Once the file is written successfully, the app assumes you will import it and
immediately marks those items as no longer pending — it does not wait for
confirmation that the Anki import itself succeeded.

## Backup and restore

```sh
english-coach backup
```

Creates a timestamped, consistent copy of the SQLite database in `data/backups/`
using SQLite's own backup API. It never overwrites an existing backup file. `init`
also takes an automatic backup before applying migrations to a database that
already has data.

To restore, stop the app, copy a backup file from `data/backups/` back over
`data/english_coach.db` (or point `config.toml` at the backup file directly), and
verify with `english-coach report progress`.

## Database location

By default: `data/english_coach.db`, relative to wherever `config.toml` lives (or
the current working directory if there is no `config.toml`). Change it via the
`[paths].database` key in `config.toml`.

## Repository layout

```text
english_coach/            application package (CLI, models, services)
alembic/                  database migrations
schemas/session_update.schema.json   generated JSON Schema for the AI contract
prompts/english_coach_system_prompt.md   the system prompt to paste into your AI
examples/                 example session-update and AI-context JSON files
data/, exports/, reports/ generated at runtime; git-ignored except for .gitkeep
tests/                    pytest suite
```

### About the example files

- `examples/session_update.example.json` is a complete, self-contained example
  (one item of every kind, `client_ref`-resolved usage events, and a memory patch)
  that validates and imports cleanly against a freshly initialized database.
- `examples/session_update_existing_item.example.json` illustrates the syntax for
  **updating** a previously known item (non-null `item_id`). Its placeholder
  `item_id` is not a real UUID — replace it with a real item UUID from your own
  `ai_context` export (or from a prior `import`'s preview) before using it; it is
  documentation, not a directly runnable fixture.
- `examples/ai_context.example.json` shows the shape of a compact AI-context export.

## Limitations and version-2 ideas

Deliberately out of scope for version 1 (see the original specification):

- No GUI/web dashboard, no local LLM, no OpenAI/AnkiConnect API integration.
- No audio generation, voice analysis, or automatic transcript analysis.
- No semantic/embedding-based deduplication — matching is deterministic
  (normalized text keys) and transparent, not fuzzy.
- Search is a safe, indexed `LIKE`-based implementation, not full-text search.

Natural version-2 directions: AnkiConnect-based direct sync, embedding-based
duplicate suggestions (with human confirmation, not silent merges), a local
dashboard, and richer analytics on accuracy trends once more session history
exists.

## Troubleshooting

- **"Database not found... Run 'init' first."** — run `english-coach init` from
  the directory containing (or intended to contain) `config.toml`.
- **Validation fails with a JSON path** — the error message includes the exact
  field path (e.g. `vocabulary[0].sense_key`); fix the AI's output at that path
  and re-run `validate`.
- **"already imported"** — the exact same `update_id` + content was imported
  before; this is expected and safe. If you intended new content, make sure the
  AI generated a fresh `update_id`.
- **Ambiguous same-file item** — two new items in one file normalized to the same
  identity (e.g. the same lemma/part-of-speech/sense combination). Either give one
  of them a distinct `sense_key`, or set its `item_id` to a real existing item UUID.
- **Anki import shows no new cards** — check `english-coach export anki --all` to
  see whether the items were already exported and unchanged (they are "pending"
  only when new or changed).
- **`--from`/`--to` rejected** — `--from` must not be later than `--to`; dates use
  `YYYY-MM-DD` and are interpreted in the configured timezone.
- **Windows: pytest reports a `PermissionError` on the Temp directory** — some
  Windows/AV setups lock the default temp folder; run
  `pytest --basetemp=.pytest_tmp` from the project root instead.

## Running the tests

```sh
pytest
# or, with coverage:
pytest --cov=english_coach --cov-report=term-missing
```

> **Windows note:** if you see a `PermissionError` on the Temp directory, run
> `pytest --basetemp=.pytest_tmp` instead.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and the
[code of conduct](CONTRIBUTING.md). Bug reports and pull requests are welcome!
Open an issue to discuss a feature or design change before implementing.
