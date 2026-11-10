"""Rocket League metrics."""

__version__ = "0.0.0"

# Stored with every metric (section 5.2 of CLAUDE.md). Any change to a definition or a computation
# moves it on, so that `just reprocess --analysis-outdated` takes the matches up again.
# 2: the game clock of the match and of its goals (A63).
# 3: touch metrics, from rl-parse 0.2.0's touches (T11.4 of docs/PLAN-V2.md).
# 4: possession and turnovers, and the first team metric (T11.5 and T11.6).
# 5: the 2D view's document gets its situations, turnovers first (T12.7).
# 6: kickoff metrics, from rl-parse 0.2.0's kickoffs (T13.1 and T13.2).
# 7: duel metrics, from its fifty_fifties and beaten_to_ball (T13.3).
ANALYSIS_VERSION = "7"
