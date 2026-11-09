# Schemas

The source of truth for the parser's output, and for the 2D view's document that the analysis
writes.

| File | Describes | Format |
|---|---|---|
| `header.schema.json` | `header.json` | JSON Schema |
| `events.schema.json` | `events.json` | JSON Schema |
| `frames.schema.json` | `frames.parquet` | Columns and types, since JSON Schema does not describe Parquet |
| `match2d.schema.json` | `views/<match_id>.json.gz`, the 2D view (`rl_analysis.view`) | JSON Schema |
| `labels.schema.json` | `tests/fixtures/labels/*.json`, the labeling mode's verdicts (T12.7) | JSON Schema |

The `ma_schemas` package loads them, validates documents and gives the worker typed dictionaries.

## Changing a format

An incompatible change bumps `schema_version` and the parser's version. Unknown fields stay accepted on reading, since a game patch can add some.

Each document has its own version: `header.json` and `frames.parquet` are at 1, `events.json` at 2 since parser 0.2.0 added subtr-actor's detections. Documents already stored are never rewritten: `parse_events` reads a version 1 `events.json` as version 2 with its four detections at `null`, which the analysis treats as "not detected".

`just test-schemas` checks the schemas against counter-examples and against the parser's real output. The parser's own tests check `frames.schema.json` against its Parquet writer.
