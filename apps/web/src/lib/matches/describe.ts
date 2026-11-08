/** Small facts about a match that its pages show, kept apart from React to be tested. */
import type { Schemas } from "@/lib/api/client";

export type MatchStatus = Schemas["MatchInfo"]["status"];

/** Statuses after which the analysis has nothing more to add. */
const SETTLED: ReadonlySet<MatchStatus> = new Set(["ready", "header_only", "failed"]);

export function inProgress(status: MatchStatus): boolean {
  return !SETTLED.has(status);
}

/**
 * The kind of game, from the playlist id the replay carries. Only the ids measured on replays or
 * stable for years are named; the others read as another mode.
 */
const PLAYLISTS: Readonly<Record<string, "casual" | "ranked" | "private">> = {
  "1": "casual",
  "2": "casual",
  "3": "casual",
  "6": "private",
  "10": "ranked",
  "11": "ranked",
  "13": "ranked",
};

export function playlistKind(playlist: string | null): "casual" | "ranked" | "private" | "other" {
  return (playlist !== null && PLAYLISTS[playlist]) || "other";
}

export function teamSize(size: number | null): string | null {
  return size ? `${size}v${size}` : null;
}

/** "m:ss" from seconds, null when unknown. */
export function duration(seconds: number | null): string | null {
  if (seconds === null || !Number.isFinite(seconds)) return null;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

type Player = Schemas["Player"];

/** Blue then orange, each by score, the way the game's scoreboard reads. */
export function byTeam(players: readonly Player[]): [Player[], Player[]] {
  const order = (a: Player, b: Player) => (b.score ?? -1) - (a.score ?? -1);
  return [
    players.filter((player) => player.team === 0).sort(order),
    players.filter((player) => player.team === 1).sort(order),
  ];
}

/** The players one may claim to be: never a bot. */
export function claimable(players: readonly Player[]): Player[] {
  return players.filter((player) => !player.is_bot);
}
