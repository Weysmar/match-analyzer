/**
 * The end criterion of step 8: a replay uploaded without an account, the player chosen, the match
 * sheet, a simulated Steam sign-in, "my stats", then the account erased and signed out (T8.14). In
 * French and in English, at 375 px (T8.15). Extended by T16.5: from the sheet to its analysis, and
 * from a situation or a goal conceded to the 2D view. Assertions never name a player.
 *
 * It uploads a real replay: it runs locally only, on demand (`just test-e2e`), never in the CI.
 */
import path from "node:path";
import { expect, type Locator, type Page, test } from "@playwright/test";

const REPLAY =
  process.env.E2E_REPLAY ??
  path.resolve(
    import.meta.dirname,
    "../../../tests/fixtures/replays/public/post-eac-ranked-doubles-2026-04-28.replay",
  );

const WORDS = {
  fr: {
    settled: /Prêt|Déjà analysé/,
    open: "Voir le match",
    question: "Lequel de ces joueurs es-tu ?",
    you: "(toi)",
    metrics: "Statistiques détaillées",
    analysis: "Analyse",
    conceded: "Buts encaissés",
    replay: /^Revoir le but/,
    replaySituation: /^Revoir/,
    replayWindow: /^Revoir les \d+ s/,
    causes: "Causes de tes buts encaissés",
    steam: "Se connecter avec Steam",
    signedIn: "Connecté : Player",
    counted: /Moyennes sur 1 match/,
    deleteAccount: "Supprimer mon compte",
    confirm: "Oui, supprimer",
    erased: "Tes données ont été supprimées.",
    signIn: "Se connecter",
    skip: "Aller au contenu",
  },
  en: {
    settled: /Ready|Already analyzed/,
    open: "Open the match",
    question: "Which of these players are you?",
    you: "(you)",
    metrics: "Detailed stats",
    analysis: "Analysis",
    conceded: "Goals conceded",
    replay: /^Replay the goal/,
    replaySituation: /^Replay/,
    replayWindow: /^Replay the \d+ s/,
    causes: "Causes of the goals you conceded",
    steam: "Sign in through Steam",
    signedIn: "Signed in: Player",
    counted: /Averages over 1 match/,
    deleteAccount: "Delete my account",
    confirm: "Yes, delete",
    erased: "Your data has been deleted.",
    signIn: "Sign in",
    skip: "Skip to content",
  },
} as const;

type Language = keyof typeof WORDS;

function words(projectName: string) {
  return WORDS[projectName as Language];
}

/** No page may scroll sideways on a phone (T8.15). */
async function fitsTheScreen(page: Page) {
  const [scroll, client] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scroll, page.url()).toBeLessThanOrEqual(client);
}

/** A link into the 2D view opens it at its `t`, paused, without scrolling sideways (T12.5). */
async function opensTheView(page: Page, link: Locator) {
  const asked = Number(
    new URLSearchParams((await link.getAttribute("href"))?.split("#")[0]).get("t"),
  );
  await link.click();
  await expect(page).toHaveURL(/\?t=[0-9.]+#view$/);
  const cursor = page.locator("#view input[type=range]");
  await expect(cursor).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(async () => Math.abs(Number(await cursor.inputValue()) - asked))
    .toBeLessThan(0.2);
  await expect(page.locator("#view button[aria-pressed=false]").first()).toBeVisible();
  await fitsTheScreen(page);
}

test("from a replay to my stats, then the account erased", async ({ page }, info) => {
  const w = words(info.project.name);

  await page.goto("/upload");
  await fitsTheScreen(page);
  await page.locator("input[type=file]").setInputFiles(REPLAY);
  const row = page.getByRole("listitem").filter({ hasText: path.basename(REPLAY) });
  // Parsing and analysis by the worker: a few seconds, more on a cold machine.
  await expect(row.getByText(w.settled)).toBeVisible({ timeout: 150_000 });

  await row.getByRole("link", { name: w.open }).click();
  await expect(page.getByRole("heading", { name: w.question })).toBeVisible();
  await fitsTheScreen(page);
  await page.locator("section[aria-labelledby=identity-question] li button").first().click();
  await expect(page.getByText(w.you, { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: w.metrics })).toBeVisible();
  await expect(page.getByRole("heading", { name: w.analysis, exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: w.conceded })).toBeVisible();

  // A goal of the timeline opens the 2D view 5 s before it, paused (T12.5).
  await opensTheView(page, page.getByRole("link", { name: w.replay }).first());

  // A situation of the analysis opens it 2 s before (T16.1), its definition on top (T16.3).
  const analysis = page.locator("section[aria-labelledby=analysis-title]");
  const situations = analysis.locator("details:has(ol)").first();
  await situations.locator("summary").click();
  await expect(situations.locator("p").first()).not.toBeEmpty();
  await opensTheView(page, situations.getByRole("link", { name: w.replaySituation }).first());

  // A goal conceded opens the start of its 10 s window (T16.2).
  const conceded = page.locator("section[aria-labelledby=conceded-title]");
  const card = conceded.locator("ol > li > details").first();
  await card.locator("summary").click();
  await opensTheView(page, card.getByRole("link", { name: w.replayWindow }));

  // The prompt under the sheet, through the stand-in for Steam (A70).
  await page.locator("aside").getByRole("link", { name: w.steam }).click();
  await expect(page.getByText(w.signedIn)).toBeVisible();
  await expect(page).toHaveURL(/\/matches\/[0-9a-f-]{36}$/);

  await page.goto("/me/stats");
  await expect(page.getByText(w.counted)).toBeVisible();
  await expect(page.locator("figure svg g[tabindex]")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: w.causes })).toBeVisible();
  await fitsTheScreen(page);

  await page.goto("/settings");
  await fitsTheScreen(page);
  await page.getByRole("button", { name: w.deleteAccount }).click();
  await page.getByRole("button", { name: w.confirm }).click();
  await expect(page.getByText(w.erased)).toBeVisible();
  await expect(page.locator("header summary", { hasText: w.signIn })).toBeVisible();
});

test("every page fits a phone", async ({ page }) => {
  for (const address of [
    "/",
    "/upload",
    "/matches",
    "/me/stats",
    "/settings",
    "/privacy",
    "/terms",
    "/legal",
  ]) {
    await page.goto(address);
    await fitsTheScreen(page);
  }
});

test("the keyboard reaches the file picker", async ({ page }, info) => {
  const w = words(info.project.name);
  await page.goto("/upload");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: w.skip })).toBeFocused();
  await page.keyboard.press("Enter");
  const picker = page.locator("input[type=file]");
  for (let stop = 0; stop < 10; stop += 1) {
    if (await picker.evaluate((element) => element === document.activeElement)) break;
    await page.keyboard.press("Tab");
  }
  await expect(picker).toBeFocused();
});
