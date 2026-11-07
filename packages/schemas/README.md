# Schemas

The source of truth for the parser's output.

| File | Describes | Format |
|---|---|---|
| `header.schema.json` | `header.json` | JSON Schema |
| `events.schema.json` | `events.json` | JSON Schema |
| `frames.schema.json` | `frames.parquet` | Columns and types, since JSON Schema does not describe Parquet |

The `ma_schemas` package loads them, validates documents and gives the worker typed dictionaries.

## Changing a format

An incompatible change bumps `schema_version` and the parser's version. Unknown fields stay accepted on reading, since a game patch can add some.

`just test-schemas` checks the schemas against counter-examples and against the parser's real output. The parser's own tests check `frames.schema.json` against its Parquet writer.
