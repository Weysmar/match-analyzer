/**
 * Drawing a scene on a 2D canvas (DV3): the field, then each car shown, then the ball with its
 * shadow. No library: seven moving things a frame, a fraction of a millisecond (T10.5). Works in
 * CSS pixels; the caller scales the context to the screen's pixel density.
 */
import { FIELD, type Layout, screenAngle, toScreen } from "./field";
import type { Scene } from "./scene";

export const COLORS = {
  field: "#14213a",
  line: "#3a4a6b",
  blue: "#3b82f6",
  orange: "#f59e0b",
  blueGoal: "rgba(59, 130, 246, 0.25)",
  orangeGoal: "rgba(245, 158, 11, 0.25)",
  boost: "#facc15",
  boostTrack: "rgba(255, 255, 255, 0.18)",
  me: "#ffffff",
  ball: "#e5e7eb",
  shadow: "rgba(0, 0, 0, 0.4)",
} as const;

/** What the drawing needs of a 2D context: a subset, so that a test can record it. */
export type Pen = Pick<
  CanvasRenderingContext2D,
  | "fillStyle"
  | "strokeStyle"
  | "lineWidth"
  | "fillRect"
  | "strokeRect"
  | "beginPath"
  | "moveTo"
  | "lineTo"
  | "stroke"
  | "arc"
  | "fill"
  | "save"
  | "restore"
  | "translate"
  | "rotate"
>;

// Cars and the ball drawn a little larger than life, and never smaller than a few pixels: on a
// phone, the field is 343 px wide and a car to scale would be 8 px long (T12.6).
const CAR_SCALE = 1.6;
const BALL_SCALE = 1.4;
export const MIN_CAR_LENGTH_PX = 14;
export const MIN_BALL_RADIUS_PX = 5;
// How much higher the ball looks per uu of height, against its shadow on the ground.
const LIFT = 0.15;

function rectangle(layout: Layout, x0: number, y0: number, x1: number, y1: number) {
  const [ax, ay] = toScreen(layout, x0, y0);
  const [bx, by] = toScreen(layout, x1, y1);
  return [Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay)] as const;
}

export function drawField(pen: Pen, layout: Layout): void {
  pen.fillStyle = COLORS.field;
  pen.fillRect(0, 0, layout.width, layout.height);
  pen.strokeStyle = COLORS.line;
  pen.lineWidth = Math.max(1, layout.scale * 20);
  pen.strokeRect(
    ...rectangle(layout, -FIELD.halfWidth, -FIELD.halfLength, FIELD.halfWidth, FIELD.halfLength),
  );
  const [ax, ay] = toScreen(layout, -FIELD.halfWidth, 0);
  const [bx, by] = toScreen(layout, FIELD.halfWidth, 0);
  pen.beginPath();
  pen.moveTo(ax, ay);
  pen.lineTo(bx, by);
  pen.stroke();
  // Blue defends y < 0, orange y > 0.
  for (const [side, color] of [
    [-1, COLORS.blueGoal],
    [1, COLORS.orangeGoal],
  ] as const) {
    pen.fillStyle = color;
    pen.fillRect(
      ...rectangle(
        layout,
        -FIELD.goalHalfWidth,
        side * FIELD.halfLength,
        FIELD.goalHalfWidth,
        side * (FIELD.halfLength + FIELD.goalDepth),
      ),
    );
  }
}

export function drawScene(pen: Pen, layout: Layout, scene: Scene, meId: number | null): void {
  drawField(pen, layout);
  const unit = layout.scale;
  for (const car of scene.cars) {
    // A car away or demolished keeps a wrong position: it is not drawn.
    if (!car.shown) continue;
    const [sx, sy] = toScreen(layout, car.x, car.y);
    const length = Math.max(MIN_CAR_LENGTH_PX, FIELD.carLength * unit * CAR_SCALE);
    const width = (length * FIELD.carWidth) / FIELD.carLength;
    pen.save();
    pen.translate(sx, sy);
    pen.rotate(screenAngle(layout, car.yaw));
    if (car.id === meId) {
      pen.fillStyle = COLORS.me;
      const ring = Math.max(2, 18 * unit);
      pen.fillRect(-length / 2 - ring, -width / 2 - ring, length + 2 * ring, width + 2 * ring);
    }
    pen.fillStyle = car.team === 0 ? COLORS.blue : COLORS.orange;
    pen.fillRect(-length / 2, -width / 2, length, width);
    pen.restore();
    // The boost under the car, always level, as wide as the car is long and then some.
    const bar = length * 1.3;
    const thickness = Math.max(2, length * 0.12);
    pen.fillStyle = COLORS.boostTrack;
    pen.fillRect(sx - bar / 2, sy + length * 0.8, bar, thickness);
    pen.fillStyle = COLORS.boost;
    pen.fillRect(sx - bar / 2, sy + length * 0.8, (bar * car.boost) / 100, thickness);
  }
  const [bx, by] = toScreen(layout, scene.ball.x, scene.ball.y);
  const radius = Math.max(MIN_BALL_RADIUS_PX, FIELD.ballRadius * unit * BALL_SCALE);
  const height = Math.max(0, scene.ball.z - FIELD.ballRadius);
  pen.fillStyle = COLORS.shadow;
  pen.beginPath();
  pen.arc(bx, by, radius, 0, Math.PI * 2);
  pen.fill();
  pen.fillStyle = COLORS.ball;
  pen.beginPath();
  pen.arc(bx, by - height * unit * LIFT, radius * (1 + height / 2000), 0, Math.PI * 2);
  pen.fill();
}
