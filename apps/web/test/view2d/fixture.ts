/**
 * A `match2d` document made by hand, as the analysis writes it: 4 s at 15 Hz. Blue (id 41) drives
 * along +x at 1000 uu/s facing +x; orange (id 42) stands at y = 500, demolished from 2 s to 3 s.
 * The ball rises from 93 to 493 uu. The clock only runs from 1 s on.
 */
const RATE = 15;
const SAMPLES = 4 * RATE + 1;

export const delta = (values: number[]) =>
  values.map((value, index) => (index === 0 ? value : value - (values[index - 1] ?? 0)));

const range = (make: (t: number, index: number) => number) =>
  Array.from({ length: SAMPLES }, (_, index) => make(index / RATE, index));

export function rawView(): Record<string, unknown> {
  return {
    version: 1,
    rate_hz: RATE,
    start_s: 10,
    samples: SAMPLES,
    delta: ["clock_ds", "ball.x", "ball.y", "ball.z", "players.x", "players.y", "players.z"],
    clock_ds: delta(range((t) => Math.round(Math.max(0, t - 1) * 10))),
    phase: range((t) => (t < 1 ? 1 : 3)),
    ball: {
      x: delta(range(() => 0)),
      y: delta(range(() => 0)),
      z: delta(range((t) => Math.round(93 + 100 * t))),
    },
    players: [
      {
        id: 41,
        team: 0,
        x: delta(range((t) => Math.round(1000 * t))),
        y: delta(range(() => -2000)),
        z: delta(range(() => 17)),
        yaw: range(() => 0),
        boost: range((t) => Math.round(100 - 10 * t)),
        flags: range(() => 1),
      },
      {
        id: 42,
        team: 1,
        x: delta(range(() => 0)),
        y: delta(range(() => 500)),
        z: delta(range(() => 17)),
        yaw: range(() => -90),
        boost: range(() => 33),
        flags: range((t) => (t >= 2 && t < 3 ? 2 : 1)),
      },
    ],
    goals: [{ time_s: 13.5, clock_s: 2.5, team: 0, player: 41 }],
    demolitions: [{ time_s: 12, attacker: 41, victim: 42 }],
    touches: [{ time_s: 11.5, player: 41 }],
  };
}
