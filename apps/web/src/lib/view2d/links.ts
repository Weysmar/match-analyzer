/**
 * Links into the 2D view (T12.5): `/matches/<id>?t=<s>#view` opens the player at `s` seconds of the
 * game clock, paused. A goal's link opens it a few seconds before, to see how it came.
 */

/** How long before a goal its link opens the view. */
export const LEAD_S = 5;
/** The id of the player's section: the link's anchor. */
export const VIEW_ANCHOR = "view";

/** The query and anchor of a link to `clockS` seconds of play, to the tenth. */
export function viewLink(clockS: number): string {
  const tenths = Math.round(Math.max(0, clockS) * 10) / 10;
  return `?t=${tenths}#${VIEW_ANCHOR}`;
}

/** The link to the moment just before a goal scored at `clockS` seconds of play. */
export function goalLink(clockS: number): string {
  return viewLink(clockS - LEAD_S);
}

/** How long before a situation its link opens the view: enough to see it start. */
export const SITUATION_LEAD_S = 2;

/** The link to the moment just before a situation at `clockS` seconds of play. */
export function situationLink(clockS: number): string {
  return viewLink(clockS - SITUATION_LEAD_S);
}

/** The `t` of the address, in seconds of play, or null when there is none or it is not a time. */
export function parseT(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value.trim() === "") return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}
