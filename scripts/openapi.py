"""Writes what the site is built from: the API's OpenAPI description to `apps/web/openapi.json`, and
the catalog of metrics (id and unit, in display order) to `apps/web/metrics.json`. `--check` fails
when either file is out of date instead, as the CI runs it.

Usage: `python scripts/openapi.py [--check]`, through `just openapi`.
"""

import json
import sys
from pathlib import Path

from ma_api.app import create_app
from ma_api.settings import Settings
from rl_analysis.registry import METRICS

WEB = Path(__file__).parents[1] / "apps/web"


def openapi() -> str:
    # The description needs no database: the address is never used.
    app = create_app(Settings(database_url="postgresql://unused@localhost/unused"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def metrics() -> str:
    catalog = [{"id": metric.id, "unit": metric.unit} for metric in METRICS]
    return json.dumps(catalog, indent=2) + "\n"


def main() -> int:
    outputs = {WEB / "openapi.json": openapi(), WEB / "metrics.json": metrics()}
    if sys.argv[1:] == ["--check"]:
        stale = [
            path.name
            for path, text in outputs.items()
            if not path.exists() or path.read_text(encoding="utf-8") != text
        ]
        for name in stale:
            print(f"apps/web/{name} is out of date: run `just openapi`", file=sys.stderr)
        return 1 if stale else 0
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print(f"written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
