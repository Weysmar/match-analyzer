/**
 * The player's controls as a pure state machine (T12.4): play and pause, speed, a jump of 5 s,
 * the cursor. Never playing by itself: the visitor starts it (section 5.6 of docs/PLAN-V2.md).
 */

export const SPEEDS = [0.5, 1, 2, 4] as const;
export type Speed = (typeof SPEEDS)[number];
export const SKIP_S = 5;

export interface Playback {
  t: number;
  playing: boolean;
  speed: Speed;
}

export type Action =
  | { type: "toggle" }
  | { type: "pause" }
  | { type: "tick"; elapsedS: number }
  | { type: "seek"; t: number }
  | { type: "skip"; byS: number }
  | { type: "speed"; speed: Speed };

export const START: Playback = { t: 0, playing: false, speed: 1 };

export function reduce(state: Playback, action: Action, durationS: number): Playback {
  const clamp = (t: number) => Math.min(durationS, Math.max(0, t));
  switch (action.type) {
    case "toggle":
      if (state.playing) return { ...state, playing: false };
      // At the end, playing again starts over.
      return { ...state, playing: true, t: state.t >= durationS ? 0 : state.t };
    case "pause":
      return { ...state, playing: false };
    case "tick": {
      if (!state.playing) return state;
      const t = clamp(state.t + action.elapsedS * state.speed);
      return { ...state, t, playing: t < durationS };
    }
    case "seek":
      return { ...state, t: clamp(action.t) };
    case "skip":
      return { ...state, t: clamp(state.t + action.byS) };
    case "speed":
      return { ...state, speed: action.speed };
  }
}

/** The keyboard, while the player has the focus: Space, then the arrows by 5 s. */
export function actionForKey(key: string): Action | null {
  switch (key) {
    case " ":
      return { type: "toggle" };
    case "ArrowLeft":
      return { type: "skip", byS: -SKIP_S };
    case "ArrowRight":
      return { type: "skip", byS: SKIP_S };
    default:
      return null;
  }
}
