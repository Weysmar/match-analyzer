"""Loads the parser's output schemas and validates documents against them."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

from ma_schemas.types import EventsDocument, HeaderDocument

__all__ = [
    "EventsDocument",
    "HeaderDocument",
    "InvalidDocumentError",
    "frames_columns",
    "frames_problems",
    "load_schema",
    "parse_events",
    "parse_header",
    "problems",
]


class InvalidDocumentError(ValueError):
    """A document does not match its schema. The message names paths, never values, since the
    documents hold player names and ids."""


def _schema_path(name: str) -> Path:
    packaged = Path(__file__).parent / name
    # In an editable install the schemas stay at the root of packages/schemas.
    return packaged if packaged.exists() else Path(__file__).parents[2] / name


@lru_cache
def load_schema(kind: str) -> dict[str, Any]:
    """`kind` is `header`, `events`, `frames`, `match2d` or `labels`."""
    text = _schema_path(f"{kind}.schema.json").read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(text))


def problems(kind: str, document: object) -> list[str]:
    """Where `document` breaks the schema, as paths and rules, without its values."""
    validator = Draft202012Validator(load_schema(kind))
    found = []
    for error in validator.iter_errors(document):
        path = "/".join(str(part) for part in error.absolute_path) or "(root)"
        found.append(f"{path}: {error.validator}")
    return sorted(found)


def _parse(kind: str, document: object) -> object:
    found = problems(kind, document)
    if found:
        raise InvalidDocumentError(f"invalid {kind}.json: " + "; ".join(found[:10]))
    return document


def parse_header(document: object) -> HeaderDocument:
    return cast(HeaderDocument, _parse("header", document))


DETECTIONS = ("touches", "kickoffs", "fifty_fifties", "beaten_to_ball")


def _upgraded(document: object) -> object:
    """A version 1 document, from a parser older than 0.2.0, read as version 2 without
    detections: the analysis treats them as not detected. Matches parsed before the V2 keep
    working without being parsed again. The caller's document is left as it was."""
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        return document
    if any(key in document for key in DETECTIONS):
        return document
    return {**document, "schema_version": 2} | dict.fromkeys(DETECTIONS)


def parse_events(document: object) -> EventsDocument:
    return cast(EventsDocument, _parse("events", _upgraded(document)))


def frames_columns() -> dict[str, str]:
    """The columns of `frames.parquet` and their types, in order."""
    return {column["name"]: column["type"] for column in load_schema("frames")["columns"]}


def frames_problems(columns: dict[str, str]) -> list[str]:
    """What differs between these `name: type` columns and the schema, order included."""
    expected = frames_columns()
    found = [f"{name}: missing" for name in expected if name not in columns]
    found += [f"{name}: unexpected" for name in columns if name not in expected]
    found += [
        f"{name}: {columns[name]} instead of {kind}"
        for name, kind in expected.items()
        if name in columns and columns[name] != kind
    ]
    if not found and list(columns) != list(expected):
        found.append("columns are in another order")
    return found
