/**
 * What the field shows at a given time: the ball and each car, interpolated between two samples.
 * A car's state (shown, demolished, boosting) is the one of the sample at or before the time: a
 * state does not interpolate.
 */
import { BOOSTING, DEMOLISHED, type Match2d, SHOWN } from "./document";
import { clockAt, lerp, lerpAngle, positionAt } from "./time";

export interface CarState {
  id: number;
  team: 0 | 1;
  x: number;
  y: number;
  z: number;
  yaw: number;
  boost: number;
  shown: boolean;
  demolished: boolean;
  boosting: boolean;
}

export interface Scene {
  t: number;
  clockS: number;
  phase: number;
  ball: { x: number; y: number; z: number };
  cars: CarState[];
}

export function sceneAt(view: Match2d, t: number): Scene {
  const at = positionAt(view, t);
  return {
    t,
    clockS: clockAt(view, t),
    phase: view.phase[at.index] ?? 0,
    ball: { x: lerp(view.ball.x, at), y: lerp(view.ball.y, at), z: lerp(view.ball.z, at) },
    cars: view.cars.map((car) => {
      const flags = car.flags[at.index] ?? 0;
      return {
        id: car.id,
        team: car.team,
        x: lerp(car.x, at),
        y: lerp(car.y, at),
        z: lerp(car.z, at),
        yaw: lerpAngle(car.yaw, at),
        boost: lerp(car.boost, at),
        shown: (flags & SHOWN) !== 0,
        demolished: (flags & DEMOLISHED) !== 0,
        boosting: (flags & BOOSTING) !== 0,
      };
    }),
  };
}
