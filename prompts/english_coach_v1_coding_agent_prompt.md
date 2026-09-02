# Build a Local AI-Powered Personal English Coach Knowledge System — Version 1

## Role

You are a senior Python engineer responsible for implementing this product end to end. Work in the current repository. Inspect existing files first, preserve unrelated work, then build and verify the application. Do not stop at architecture or pseudocode. Produce working code, migrations, tests, sample data, prompts, and documentation.

Use reasonable implementation judgment within this specification. Ask a question only if a genuine blocker cannot be resolved from the requirements. Do not add unrelated features.

## Product goal

Build a local-first personal English-learning knowledge system with SQLite as its source of truth. The learner talks to an external AI such as ChatGPT, manually receives a structured JSON session update, previews it locally, approves it, and then imports it into the knowledge base. The same Python application exports:

1. polished Anki material, primarily as an `.apkg` file suitable for direct import into Anki/AnkiDroid;
2. a compact JSON context bundle for the next AI session;
3. readable Markdown reports for the learner.

The system is a knowledge and coaching-memory layer. It must not reproduce Anki's scheduling algorithm.

## Learner profile and language policy

- Native language: Persian.
- Current level: B1–B2.
- Target: C1 within approximately six months.
- Daily study time: 30 minutes.
- English variety: American English.
- IPA: General American pronunciation.
- Main uses: international professional communication, meetings, technical explanations, leadership, product management, robotics/software/AI discussions, technical and behavioral interviews, presentations, networking, and possible PhD applications.
- Persian meanings are optional. Include them only when a word or expression is difficult enough that a clear B1–B2 English definition is unlikely to be sufficient.

## Fixed version-1 decisions

- The application is local and makes no AI API calls.
- Exchanging files with the AI is manual.
- SQLite is the only authoritative knowledge store.
- The user must see a detailed preview before any session update changes SQLite.
- An import occurs only after explicit confirmation.
- Semantic AI-to-AI validation is out of scope, but strict structural validation is mandatory.
- Imports must be atomic and idempotent.
- The database must never store Anki intervals, ease factors, due dates, or scheduling history.
- There is no GUI, web dashboard, local LLM, OpenAI API integration, AnkiConnect integration, audio generation, voice analysis, semantic embedding deduplication, or automatic transcript analysis in version 1.
- Do not store complete conversation transcripts. Store summaries, selected evidence snippets, learning items, mistakes, usage events, and coaching memory.
- There is no fixed numeric limit on items imported from an AI session. The AI decides which items are durable and useful enough for the knowledge base.
- Anki export has no item-count limit. By default it exports every pending item. Optional inclusive date filters are supported.
- After an Anki file is generated successfully, assume the user will import it. Do not wait for import confirmation.
- Human approval authorizes the displayed changes. No AI-originated update may silently overwrite existing content.

## System flow

```text
SQLite knowledge base
    -> compact AI-context JSON/Markdown export
    -> human uploads context to AI and has an English session
    -> AI produces versioned session-update JSON
    -> Python validates and resolves references
    -> Python displays a human-readable change preview
    -> human confirms or rejects
    -> one atomic SQLite transaction applies the complete update
    -> Python creates a session report
    -> Python exports pending Anki notes and future AI context
```

## Technology

Use:

- Python 3.12+
- SQLite
- SQLAlchemy 2.x
- Alembic migrations
- Pydantic 2.x for strict input and output contracts
- Typer for the CLI
- Rich for readable previews and terminal reports
- genanki for `.apkg` generation
- pytest, pytest-cov, and Typer's CLI test runner
- standard-library `json`, `csv`, `hashlib`, `uuid`, `datetime`, `zoneinfo`, `pathlib`, `html`, and `logging` where applicable

The implementation must work on Windows and remain cross-platform. Use `pathlib`; do not depend on shell-specific path behavior. Store database timestamps in UTC ISO-8601 form. Use `Asia/Tehran` as the default display and date-filter timezone, configurable in a local TOML configuration file.

## Required repository structure

Use a clear package layout equivalent to:

```text
.
├── pyproject.toml
├── README.md
├── alembic.ini
├── alembic/
├── config.example.toml
├── english_coach/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── schemas.py
│   ├── normalization.py
│   ├── mastery.py
│   ├── services/
│   │   ├── importer.py
│   │   ├── preview.py
│   │   ├── deduplication.py
│   │   ├── context_exporter.py
│   │   ├── report_generator.py
│   │   ├── anki_exporter.py
│   │   └── backup.py
│   └── templates/
│       ├── anki/
│       └── reports/
├── schemas/
│   └── session_update.schema.json
├── prompts/
│   └── english_coach_system_prompt.md
├── examples/
│   ├── session_update.example.json
│   └── ai_context.example.json
├── data/
│   ├── imported/
│   ├── backups/
│   └── .gitkeep
├── exports/
│   └── .gitkeep
├── reports/
│   └── .gitkeep
└── tests/
```

Do not commit a generated user database, exports, reports, backups, or imported private session files. Configure `.gitignore` accordingly.

Provide both an installed command named `english-coach` and `python -m english_coach`.

## Database model

Use explicit foreign keys, check constraints, unique constraints, and indexes. Enable SQLite foreign-key enforcement for every connection.

### `learner_profile`

Enforce exactly one current row using `id = 1` and a database check constraint.

Store:

- native language;
- current and target CEFR levels;
- English variety and pronunciation standard;
- daily study minutes;
- Persian-meaning policy;
- professional background as validated JSON;
- learning goals as validated JSON;
- default timezone;
- creation and update timestamps.

Seed the row with the profile in this specification during `init`.

### `sessions`

Store:

- stable UUID primary key supplied by the session update;
- start and end timestamps when available;
- local session date;
- topic;
- session type;
- summary;
- strengths, weak points, next-focus suggestions, and fluency notes as validated JSON;
- source import batch;
- creation timestamp.

Do not store the full transcript.

### `import_batches`

Store:

- internal UUID;
- globally unique `update_id` from the AI output;
- JSON schema version;
- original filename;
- SHA-256 hash of normalized input bytes;
- the approved raw JSON;
- applied timestamp;
- result summary.

Both `update_id` and the content hash must be unique. Re-importing the same update must be a safe no-op that reports the original import. If an existing `update_id` is supplied with different content, reject it as a conflict.

Previewing or rejecting a file must not insert an import-batch record or mutate any application table.

### `learning_items`

Use a common parent table for vocabulary, expressions, grammar patterns, and mistakes.

Store:

- stable UUID primary key;
- `kind`: `vocabulary`, `expression`, `grammar`, or `mistake`;
- normalized deduplication key;
- display text;
- nullable CEFR level;
- importance score from 1 to 10;
- computed mastery score from 0 to 100;
- computed mastery status;
- nullable manual mastery override;
- total qualifying usage count;
- correct qualifying usage count;
- first-learned timestamp;
- last-used timestamp;
- source session UUID;
- revision number starting at 1;
- created and updated timestamps;
- nullable archived timestamp.

Use a uniqueness rule based on `(kind, deduplication_key)`. Do not use the mutable English definition as the sole identity.

### Type-specific detail tables

Use one-to-one detail tables keyed by `learning_items.id`.

`vocabulary_details` must store:

- word and lemma;
- part of speech;
- short stable `sense_key` used to distinguish meanings of the same lemma;
- clear English meaning;
- optional Persian meaning;
- General American IPA and optional stress note;
- usage note;
- common errors as validated JSON.

Construct the vocabulary deduplication key from normalized lemma, part of speech, and sense key.

`expression_details` must store:

- expression text;
- expression type: idiom, phrasal verb, collocation, professional expression, sentence chunk, or other;
- English meaning;
- optional Persian meaning;
- General American IPA when useful;
- usage contexts as validated JSON;
- common errors as validated JSON.

`grammar_details` must store:

- pattern name;
- English explanation;
- optional Persian explanation under the same difficulty policy;
- reusable structure;
- the learner's specific problem;
- common errors as validated JSON.

`mistake_details` must store:

- original wrong sentence;
- corrected sentence;
- category;
- English explanation;
- optional Persian explanation;
- severity: low, medium, or high;
- state: active, improving, or resolved;
- occurrence count.

### `item_examples`

Store examples separately so new unique examples can be appended without replacing earlier examples. Include the item UUID, sentence, optional note, source session, normalized sentence, and timestamps. Prevent duplicate normalized examples for the same item.

### `tags` and `item_tags`

Support reusable many-to-many topic tags. Normalize tag identity without destroying the original display form.

### `usage_events`

Every event must reference a real learning-item UUID and session UUID.

Store:

- stable event UUID;
- item UUID;
- session UUID;
- event type: `user_production`, `prompted_recall`, `coach_introduction`, or `mistake_occurrence`;
- nullable correctness;
- short evidence context;
- optional correction;
- occurrence timestamp.

Only `user_production` and `prompted_recall` events with non-null correctness affect mastery counters. Merely teaching an item must not count as learner usage. Prevent duplicate events from the same imported update.

### `memory_state`

Enforce one current row with `id = 1`. Store current topics, active goals, weak points, completed topics, next-session focus, last-session UUID, and update timestamp as strictly validated JSON values.

Apply `memory_patch` operations explicitly. Do not replace the entire memory object with an unvalidated AI blob. Keep only one current memory row; historical changes belong in the audit log.

### `item_revisions`

For every approved change to an existing item, store the item UUID, session UUID, revision number, before JSON, after JSON, change source, and timestamp. This provides audit and rollback evidence without creating multiple current item records.

### `anki_export_batches` and `anki_export_items`

Record each successfully written Anki export, including filename, format, filters, SHA-256 hash, item count, and timestamp. Record the exported item UUID, item revision, and exact exported-content hash.

An item is pending Anki export when:

- it has never appeared in a successful export; or
- its current exported-content hash differs from the most recently recorded hash.

This replaces the unreliable `anki_exported` Boolean while retaining the user's simple workflow. Once the file is written successfully, record the export immediately and assume it will be imported.

## Canonical AI session-update contract

Implement strict Pydantic models with `extra='forbid'` and generate `schemas/session_update.schema.json` from those models. The root object must have this shape:

```json
{
  "schema_version": "1.0",
  "update_id": "UUID",
  "generated_at": "timezone-aware ISO-8601 timestamp",
  "language_standard": "en-US",
  "session": {},
  "vocabulary": [],
  "expressions": [],
  "grammar_patterns": [],
  "mistakes": [],
  "usage_events": [],
  "memory_patch": {}
}
```

### Session object

Require:

- `session_id`: UUID;
- `ended_at`: timezone-aware timestamp;
- `topic`: non-empty string;
- `session_type`: conversation, technical_interview, behavioral_interview, leadership, professional_communication, presentation, academic, or other;
- `summary`: concise English summary;
- `strengths`: string array;
- `weak_points`: string array;
- `fluency_notes`: string array;
- `next_focus`: string array.

Allow nullable `started_at`.

### Common item fields

Every item in every type array must include:

- `client_ref`: a unique, human-readable reference within this file;
- nullable `item_id`: use the stable UUID from the supplied AI context when updating a known item; use null for a new item;
- `importance_score`: integer 1–10;
- nullable CEFR level;
- `topics`: deduplicated string array;
- `source_context`: a short exact or faithful excerpt showing why the item matters;
- `selection_reason`: why this deserves durable storage;
- `observed_from`: user, coach, or both.

The arrays themselves are the selected knowledge-base payload. Do not add a redundant `selected` Boolean.

Vocabulary additionally requires word, lemma, part of speech, short sense key, English meaning, nullable Persian meaning, nullable General American IPA, nullable stress note, examples, collocations, usage note, and common errors.

Expressions additionally require expression, expression type, English meaning, nullable Persian meaning, nullable General American IPA, examples, usage contexts, and common errors.

Grammar patterns additionally require pattern name, English explanation, nullable Persian explanation, structure, examples, learner-specific problem, and common errors.

Mistakes additionally require wrong sentence, corrected sentence, category, English explanation, nullable Persian explanation, severity, evidence, additional examples, and occurrences in this session.

Persian meaning fields must normally be null. They are populated only when a concise English explanation is probably inadequate for this B1–B2 Persian-speaking learner.

### Usage-event references

Each usage event must include:

- `event_id`: UUID;
- exactly one of `item_id` or `client_ref`;
- event type;
- nullable correctness;
- evidence context;
- nullable correction;
- occurrence timestamp.

The importer must resolve `client_ref` to an item created or matched in the same transaction. Reject missing, ambiguous, or cross-type references before showing an approvable preview.

### Memory patch

Use explicit fields:

- `current_topics_add` and `current_topics_remove`;
- `active_goals_add` and `active_goals_remove`;
- `completed_topics_add`;
- `weak_points_upsert`, with stable key, description, severity, evidence, and last-seen timestamp;
- `weak_points_resolved`, containing stable weak-point keys;
- `next_session_focus`, which replaces only that list.

Normalize and deduplicate list values while preserving display text.

### Input robustness

Accept UTF-8 JSON with or without a UTF-8 BOM. Prefer raw JSON. For practical manual copying, also accept exactly one outer Markdown `json` code fence when no other text exists. Reject comments, trailing prose, multiple JSON objects, NaN, duplicate object keys, and unknown fields. Display validation failures with JSON paths and actionable messages.

Write a complete valid example file containing at least one item of every kind, an update to an existing item, resolved client references, usage events, and a memory patch.

## Import, preview, approval, and transaction behavior

Implement:

```text
english-coach validate SESSION_UPDATE.json
english-coach import SESSION_UPDATE.json
english-coach import SESSION_UPDATE.json --yes
```

`validate` performs parsing, schema validation, reference validation, and duplicate-resolution analysis without mutation.

`import` must:

1. parse and validate the complete document;
2. check update ID and content-hash idempotency;
3. resolve existing IDs, normalized deduplication matches, and same-file client references;
4. calculate the complete proposed transaction in memory;
5. display a Rich preview grouped into new items, matched items, field updates, appended examples/tags, usage events, counter/mastery changes, memory changes, and warnings;
6. ask `Apply all displayed changes? [y/N]`;
7. perform no mutation when the answer is not an explicit yes;
8. apply all approved changes in one database transaction;
9. roll back everything on any failure;
10. copy the approved canonical JSON into `data/imported/` and record its import batch only after successful commit;
11. generate a Markdown session report.

`--yes` skips the interactive question but must still print the preview. It exists for trusted automation and tests; document its risk.

Do not increment usage counters directly from item presence. Derive changes from qualifying usage events only.

## Duplicate and merge rules

Implement deterministic, transparent version-1 deduplication without embeddings:

- Unicode NFKC normalization;
- case folding where appropriate;
- trim and collapse whitespace;
- normalize common smart apostrophes and dash variants;
- preserve the original display text;
- vocabulary identity uses lemma + part of speech + sense key;
- expression identity uses normalized expression text;
- grammar identity uses normalized pattern name;
- mistake identity uses normalized wrong sentence + corrected sentence + category.

If an incoming valid `item_id` exists and has the correct type, it wins over text matching. If the ID has the wrong type, reject the import. If an item has no ID and resolves to one unambiguous deduplication key, propose an update. If resolution is ambiguous, reject approval and instruct the user to edit the JSON with an existing item UUID or a distinct vocabulary sense key.

Merge unique examples, topics, collocations, usage contexts, and common-error entries. For changed scalar content, show old and new values in the preview. Apply the displayed replacement only after confirmation. Never make silent scalar replacements.

## Mastery estimation

Mastery represents observed conversational production and recall, not Anki scheduling.

Count only qualifying `user_production` and `prompted_recall` events. Compute:

```text
accuracy = correct qualifying events / all qualifying events
accuracy_component = round(50 * accuracy)
volume_component = min(30, qualifying_event_count * 3)
session_component = min(20, distinct_qualifying_session_count * 4)
mastery_score = accuracy_component + volume_component + session_component
```

When there are no qualifying events, the score is 0.

Map status as follows:

- `new`: zero qualifying events;
- `learning`: score 1–39;
- `practicing`: score 40–69;
- `strong`: score 70–89;
- `mastered`: score at least 90, at least 12 qualifying events, at least five distinct sessions, accuracy at least 90%, and the latest three qualifying events are correct.

A nullable manual override may set the displayed status without altering the underlying score or event history. Reports must clearly label overrides.

For mistakes, set `resolved` only after at least five correct qualifying attempts across at least three sessions since the most recent mistake occurrence, or by explicit human override. Otherwise use `active` or `improving` based on recent evidence.

## AI-context export

Implement:

```text
english-coach export ai-context
english-coach export ai-context --full
```

Default output:

```text
exports/ai_context_YYYYMMDD_HHMMSS.json
exports/ai_context_YYYYMMDD_HHMMSS.md
```

The default compact context must include:

- learner profile and language policy;
- active goals;
- all active weak points;
- next-session focus;
- summaries of the five most recent sessions;
- unresolved or recurring mistakes ordered by severity, frequency, and recency;
- the highest-priority non-mastered vocabulary, expressions, and grammar, ordered by importance, low mastery, and recency;
- recently learned material that should receive active recall;
- stable item UUIDs for every included item;
- summary counts for omitted material;
- a short machine instruction explaining that the AI must reuse supplied IDs, distinguish user production from coach introduction, and never invent prior usage.

Keep the default context compact enough for practical manual upload. Use a documented configurable item budget with a sensible default. `--full` includes every non-archived item and is explicitly documented as potentially large.

The Markdown form is for human inspection. The JSON form is authoritative for AI input.

## Human-readable reports and search

Implement:

```text
english-coach report latest
english-coach report session SESSION_ID
english-coach report progress
english-coach search QUERY
english-coach item show ITEM_ID
```

After every successful import, create a session report containing:

- session summary;
- strengths and weak points;
- newly created and updated learning items;
- important corrections;
- usage and mastery changes;
- memory-state changes;
- recommended next-session focus.

The progress report includes counts by type and mastery status, accuracy trends, active recurring mistakes, recently practiced material, strongest areas, weak areas, and recommended focus. Do not claim statistical trends when insufficient sessions exist; state the limitation.

Search must cover display text, English/Persian meanings, examples, tags, structures, wrong sentences, and corrected sentences. A safe indexed `LIKE` implementation is acceptable for version 1; FTS5 is optional only if it remains simple and well tested.

## Anki and AnkiDroid export

Implement:

```text
english-coach export anki
english-coach export anki --from YYYY-MM-DD --to YYYY-MM-DD
english-coach export anki --all
english-coach export anki --format tsv
```

Behavior:

- Default format is `.apkg` using genanki.
- Default selection is every pending item: never exported or changed since its last export.
- There is no item-count limit.
- `--from` and `--to` are optional inclusive filters on the learner's local `first_learned_date`. Either bound may be supplied independently.
- Validate that `from <= to`.
- `--all` includes all matching non-archived items even if previously exported.
- If nothing matches, report that clearly and do not create an empty package or export record.
- Only record a successful export after the final file has been written and hashed.
- A later content change must make the item pending again.
- Use deterministic note GUIDs derived from stable item UUIDs and stable, hard-coded model IDs. Re-exporting must update matching notes rather than create duplicates.
- Do not include scheduling information.

Create these subdecks inside one package:

```text
English Coach::Vocabulary
English Coach::Expressions
English Coach::Grammar
English Coach::Mistakes
```

Use one tailored note model and one card per learning item for each type. Avoid reverse cards in version 1 to prevent unnecessary card multiplication.

### Card design

Create polished, mobile-first HTML/CSS without external fonts, JavaScript, or network assets. It must render cleanly in Anki desktop and AnkiDroid, support narrow screens, and include a `.nightMode` dark theme.

Visual requirements:

- restrained professional design;
- clear type badge and visual hierarchy;
- comfortable font size and line height;
- maximum readable width with responsive padding;
- distinct blocks for meaning, pronunciation, examples, usage, and notes;
- Persian fields use `dir="rtl"`, right alignment, and appropriate line height;
- no decorative clutter or tiny metadata;
- safe escaped HTML and `<br>` conversion;
- consistent colors across note types with a different accent per type.

Card content:

- Vocabulary front: word, part of speech, optional topic/context cue, and a recall prompt. Back: General American IPA, clear English meaning, optional Persian meaning, natural examples, useful collocations, usage note, common errors, CEFR, and tags.
- Expression front: expression and a context/meaning recall prompt. Back: meaning, optional Persian meaning, IPA when useful, usage contexts, natural examples, and common mistakes.
- Grammar front: pattern name plus structure or a short completion prompt. Back: concise explanation, reusable structure, examples, learner-specific problem, and common errors.
- Mistake front: the learner's wrong sentence with a prompt to correct it. Back: corrected sentence, concise explanation, optional Persian explanation, and additional examples.

The app-owned stable UUID must be present in a hidden or unobtrusive `CoachID` field for reliable updates.

The TSV fallback must be UTF-8, use tabs, use the stable app-owned ID as its first ordinary field, include Anki import headers where supported, quote/escape fields correctly, and generate one file per note type plus a short import-instructions Markdown file.

## Revised AI coach prompt

Create `prompts/english_coach_system_prompt.md` as a finished reusable prompt, not a placeholder. Preserve the learner profile and professional goals from this specification while fixing these defects in the original concept:

- Do not force three words, two collocations, one phrasal verb, and one expression after every learner message. That fixed quota overwhelms a 30-minute session and conflicts with natural conversation.
- During normal conversation, correct only the highest-value errors and teach vocabulary organically.
- Keep detailed durable tracking internally during the session, then export selected items at the explicit `/export` command.
- At session start, use an uploaded AI-context JSON when present. Prefer its next-focus and active weak points; avoid repeating recent topics without reason.
- Use American English and General American IPA.
- Use Persian explanations only under the stated difficulty policy.
- Do not infer pronunciation errors from text. Assess pronunciation only when actual audio or reliable pronunciation evidence is available; otherwise mark it unassessed.
- Distinguish material introduced by the coach from material actually produced or recalled by the learner.
- Reuse existing item UUIDs supplied in the context.
- Never invent past sessions, usage, mastery, or mistakes.
- When the user enters `/export`, return exactly one valid session-update JSON object conforming to version 1.0, with no prose or Markdown fence. If the interface supports creating a downloadable JSON file, it may additionally provide the same exact bytes as a file, but the response content itself must remain valid JSON.
- Include no fixed number of knowledge items. Include every item that is genuinely durable, useful, personalized, and supported by the session; omit filler and one-off trivial words.

Include the canonical output fields and a compact example in the prompt. Keep the prompt and generated JSON Schema synchronized through a test or a shared generated example.

## Configuration and backup

Create `config.example.toml` with documented paths, timezone, deck names, default context budget, and learner profile values. Load an optional user `config.toml`; otherwise use safe defaults.

Implement:

```text
english-coach init
english-coach backup
```

`init` creates directories, applies all migrations, seeds singleton rows, and is safe to run repeatedly.

`backup` creates a timestamped, consistent SQLite backup in `data/backups/` using SQLite's backup API. Before applying future migrations to a non-empty database, create a backup automatically. Never overwrite an existing backup.

Use rotating local logs without recording complete private input JSON or full evidence snippets at normal log levels.

## Error handling

- Use concise user-facing errors and non-zero exit codes.
- Never print a Python traceback for expected validation or CLI errors unless `--debug` is enabled.
- Detect a missing/uninitialized database and tell the user to run `init`.
- Handle locked database, invalid paths, unwritable output directories, invalid dates, invalid UUIDs, malformed UTF-8, and failed package generation.
- Do not leave temporary or partial output files. Write to a temporary file in the destination directory, flush, then replace atomically.

## Tests

Create isolated tests using temporary directories and databases. At minimum test:

1. fresh initialization and repeat initialization;
2. strict JSON validation and useful JSON-path errors;
3. BOM and single-code-fence input handling;
4. rejection of trailing text, duplicate keys, unknown fields, and bad cross-references;
5. normalization and exact duplicate matching;
6. different vocabulary senses not being merged;
7. known `item_id` upsert behavior;
8. same-file `client_ref` resolution;
9. preview and rejection causing zero database changes;
10. successful atomic import;
11. forced mid-import failure rolling back every table;
12. duplicate update and duplicate hash being idempotent;
13. same update ID with different content being rejected;
14. usage counters ignoring coach introductions;
15. mastery score and status boundaries;
16. singleton memory patch merge behavior;
17. scalar changes and appended examples appearing in preview;
18. audit revision creation;
19. human session and progress reports;
20. compact AI-context content, stable IDs, and absence of transcripts;
21. pending Anki selection;
22. changed exported items becoming pending again;
23. inclusive date-range filtering and invalid range rejection;
24. deterministic Anki note GUIDs and stable models/decks;
25. successful non-empty `.apkg` generation;
26. UTF-8 TSV output, Persian text, newlines, tabs, quotes, and HTML escaping;
27. empty export behavior;
28. one end-to-end fixture: validate -> preview -> approve -> query -> report -> AI context -> Anki export.

Use coverage to find untested core branches. Do not chase 100% coverage at the expense of meaningful behavior, but core importer, deduplication, mastery, context export, and Anki export logic must be directly tested.

## Documentation

Write a practical README containing:

- product purpose and privacy boundary;
- installation in a virtual environment on Windows, macOS, and Linux;
- exact commands;
- the complete manual AI workflow;
- how to upload AI context and invoke `/export`;
- preview/approval behavior;
- Anki/AnkiDroid `.apkg` import;
- TSV fallback instructions;
- export-pending and date-filter semantics;
- backup and restore;
- database location;
- limitations and version-2 ideas;
- troubleshooting.

Do not claim that local storage makes the external AI conversation private. State that the database is local but any content manually sent to a cloud AI is subject to that service.

## Acceptance criteria

The work is complete only when all of the following are true:

- A fresh checkout can be installed from `pyproject.toml`.
- `english-coach init` creates a usable local database.
- The supplied example session update validates.
- `english-coach import` displays a detailed preview and does not mutate before approval.
- Approval applies one complete, idempotent transaction.
- Duplicate and update behavior is deterministic and auditable.
- A human-readable session report is generated.
- AI-context JSON and Markdown are generated with stable IDs and useful past context.
- A styled `.apkg` with the four subdecks imports without duplicate note identities.
- The pending-export state changes only after successful file generation and resets when content changes.
- Optional inclusive date filters work with no numeric limit.
- No Anki scheduling data is stored or generated.
- Tests pass from a clean environment.
- README instructions reproduce the full workflow.

## Execution and final response

Implement the application now. Run the most relevant tests, package/build checks, and a CLI smoke test. Inspect at least one rendered Anki card representation by testing the generated HTML/CSS at narrow and normal widths; correct clipping, broken RTL layout, escaping, and dark-mode defects before finishing.

In the final response, lead with the completed outcome. List important files, exact commands to try, validation performed, and any remaining limitation. If a required validation cannot run, state the reason and the next-best check. Do not report completion while tests or core acceptance criteria are knowingly failing.
