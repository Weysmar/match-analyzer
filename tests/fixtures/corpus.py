"""Replay corpus. `fetch` downloads the public replays, `check` verifies them against the manifest.

Replays are never versioned, since they hold other players' names and ids: only the manifest of
the public ones is. `write` regenerates that manifest from the files present.
"""

import hashlib
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
REPLAYS = ROOT / "replays"
MANIFEST = ROOT / "manifest.toml"
SOURCE = (
    "https://raw.githubusercontent.com/rlrml/subtr-actor/"
    "ea9f34d5f9d6a20fff5fd73768c04975c3f5b7e4/assets/"
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write() -> None:
    lines = [f'source = "{SOURCE}"', ""]
    paths = sorted((REPLAYS / "public").glob("*.replay"))
    for path in paths:
        sha = digest(path.read_bytes())
        lines += ["[[public]]", f'name = "{path.name}"', f'sha256 = "{sha}"', ""]
    MANIFEST.write_text("\n".join(lines), encoding="utf-8")
    print(f"manifest: {len(paths)} public replays")


def fetch() -> int:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    target = REPLAYS / "public"
    target.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for entry in manifest["public"]:
        path = target / entry["name"]
        if path.exists() and digest(path.read_bytes()) == entry["sha256"]:
            continue
        with urllib.request.urlopen(manifest["source"] + entry["name"], timeout=60) as response:
            data = response.read()
        if digest(data) != entry["sha256"]:
            print(f"BAD DOWNLOAD {entry['name']}")
            return 1
        path.write_bytes(data)
        downloaded += 1
    print(f"public: {downloaded} downloaded, {len(manifest['public']) - downloaded} already here")
    return 0


def check() -> int:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = 0
    for entry in manifest["public"]:
        path = REPLAYS / "public" / entry["name"]
        if not path.exists() or digest(path.read_bytes()) != entry["sha256"]:
            print(f"BAD {entry['name']}")
            bad += 1
    print(f"public: {len(manifest['public'])} in manifest, {bad} bad")
    for group in ("legacy", "vincent"):
        print(f"{group}: {len(list((REPLAYS / group).glob('*.replay')))} files")
    return 1 if bad else 0


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["write"]:
            write()
        case ["fetch"]:
            sys.exit(fetch())
        case _:
            sys.exit(check())
