"""Writes the API's OpenAPI description to `apps/web/openapi.json`, which the site's client is
generated from. `--check` fails when the file is out of date instead, as the CI runs it.

Usage: `python scripts/openapi.py [--check]`, through `just openapi`.
"""

import json
import sys
from pathlib import Path

from ma_api.app import create_app
from ma_api.settings import Settings

TARGET = Path(__file__).parents[1] / "apps/web/openapi.json"


def document() -> str:
    # The description needs no database: the address is never used.
    app = create_app(Settings(database_url="postgresql://unused@localhost/unused"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    text = document()
    if sys.argv[1:] == ["--check"]:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print("apps/web/openapi.json is out of date: run `just openapi`", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"written: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
