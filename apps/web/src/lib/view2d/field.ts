/**
 * The field seen from above, to scale (section 7 of CLAUDE.md), and where a point of it lands on
 * the canvas. Upright on a phone, blue defending the bottom; on its side on a computer, blue
 * defending the left. Both are the same picture turned a quarter, never mirrored.
 */

export const FIELD = {
  halfWidth: 4096,
  halfLength: 5120,
  goalDepth: 880,
  goalHalfWidth: 893,
  ballRadius: 93,
  carLength: 118,
  carWidth: 84,
} as const;

export type Orientation = "upright" | "sideways";

/** From this width of the player on, the field lies on its side. */
export const SIDEWAYS_FROM_PX = 640;

export interface Layout {
  orientation: Orientation;
  /** CSS pixels. */
  width: number;
  height: number;
  /** CSS pixels per uu. */
  scale: number;
}

const LONG = 2 * (FIELD.halfLength + FIELD.goalDepth);
const SHORT = 2 * FIELD.halfWidth;

/** The largest field that fits `width` by `maxHeight`, on its side when there is room. */
export function layoutFor(width: number, maxHeight: number): Layout {
  const orientation: Orientation = width >= SIDEWAYS_FROM_PX ? "sideways" : "upright";
  const [across, along] = orientation === "sideways" ? [LONG, SHORT] : [SHORT, LONG];
  const scale = Math.max(0, Math.min(width / across, maxHeight / along));
  return { orientation, width: across * scale, height: along * scale, scale };
}

/** A field point, in uu, on the canvas, in CSS pixels. */
export function toScreen(layout: Layout, x: number, y: number): [number, number] {
  const { scale } = layout;
  if (layout.orientation === "sideways") {
    return [(y + FIELD.halfLength + FIELD.goalDepth) * scale, (x + FIELD.halfWidth) * scale];
  }
  return [(x + FIELD.halfWidth) * scale, (FIELD.halfLength + FIELD.goalDepth - y) * scale];
}

/** A heading on the field (degrees, 0 towards +x) as an angle on the canvas, in radians. */
export function screenAngle(layout: Layout, yawDegrees: number): number {
  const radians = (yawDegrees * Math.PI) / 180;
  const [x0, y0] = toScreen(layout, 0, 0);
  const [x1, y1] = toScreen(layout, Math.cos(radians), Math.sin(radians));
  return Math.atan2(y1 - y0, x1 - x0);
}
