"""Duels (T13.3 of docs/PLAN-V2.md), read from the parser's `fifty_fifties` and `beaten_to_ball`
(DV7): subtr-actor's detectors, used as they are.

A duel is a 50/50: a player of each team touching the ball within a short time of each other. The
kickoff's own 50/50 is one too, as subtr-actor counts it. Who won it is, as the plan defines it,
the team with the ball when it settles (`possession_team`), not subtr-actor's `winner_team`, which
judges the contact itself: the two differ in 43 % of the duels of the corpus.

Beaten to the ball: a player who was going for the ball, fast and aligned, and whom an opponent
reached first (subtr-actor's `beaten_to_ball`, its own thresholds).

A match parsed before rl-parse 0.2.0, without these lists, has none of these metrics.
"""

from collections import Counter

from rl_analysis.frames import PerPlayer
from rl_analysis.match import Match


def _contested(match: Match) -> tuple[Counter[int], Counter[int]] | None:
    """For each player, the duels they contested and those their team came out of with the ball."""
    duels = match.events["fifty_fifties"]
    if duels is None:
        return None
    contested: Counter[int] = Counter()
    won: Counter[int] = Counter()
    for duel in duels:
        for player, team in ((duel["blue_player_idx"], 0), (duel["orange_player_idx"], 1)):
            if player is None:
                continue
            contested[player] += 1
            won[player] += duel["possession_team"] == team
    return contested, won


def count(match: Match) -> PerPlayer:
    """`duel.count`: 50/50s the player contested, kickoff ones included. A count."""
    found = _contested(match)
    if found is None:
        return dict.fromkeys(match.players)
    contested, _ = found
    return {player: float(contested[player]) for player in match.players}


def won_share(match: Match) -> PerPlayer:
    """`duel.won_pct`: share of the player's 50/50s after which their team has the ball; one that
    leaves it loose is not won. In %; None when the player contested none."""
    found = _contested(match)
    if found is None:
        return dict.fromkeys(match.players)
    contested, won = found
    return {
        player: 100.0 * won[player] / contested[player] if contested[player] else None
        for player in match.players
    }


def beaten(match: Match) -> PerPlayer:
    """`duel.beaten`: times the player, going for the ball, was beaten to it by an opponent. A
    count."""
    found = match.events["beaten_to_ball"]
    if found is None:
        return dict.fromkeys(match.players)
    times = Counter(event["player_idx"] for event in found)
    return {player: float(times[player]) for player in match.players}
