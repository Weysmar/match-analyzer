"""A match as the metrics read it: the frames, and the events that come with them."""

import json
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ma_schemas import EventsDocument, parse_events
from rl_analysis import frames as frames_module


@dataclass(frozen=True)
class Match:
    frames: pl.DataFrame
    events: EventsDocument

    @property
    def players(self) -> list[int]:
        """Every player of the roster, those without a frame included."""
        return sorted(member["player_idx"] for member in self.events["roster"])

    def team_of(self, player: int) -> int:
        return next(m["team"] for m in self.events["roster"] if m["player_idx"] == player)


def load(frames_path: Path, events_path: Path) -> Match:
    """Both files as `rl-parse` writes them, checked against their schemas."""
    events = parse_events(json.loads(events_path.read_text(encoding="utf-8")))
    return Match(frames_module.read(frames_path), events)
