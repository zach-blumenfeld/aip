import { expect, type Locator, type Page } from "@playwright/test";

// What the specs do on the run page, in one place: the forms are a field per key (views/Run.tsx), a
// text area for a string, radios for an answer with labels or a true_or_false.

const field = (scope: Locator, key: string) => scope.locator(`[data-testid="field"][data-key="${key}"]`);

/** Type `value` into the field of `key` (a string, a number, or JSON for a list or an object). */
export async function fill(scope: Locator, key: string, value: string): Promise<void> {
  await field(scope, key).getByLabel(key, { exact: true }).fill(value);
}

/** Pick `option` for `key`: a label of a choice or a score, or `true` / `false`. */
export async function pick(scope: Locator, key: string, option: string): Promise<void> {
  await field(scope, key).getByRole("radio", { name: option, exact: true }).check();
}

/** Open the run page of `ref` and start a run with string inputs; other inputs are given as JSON text. */
export async function start(page: Page, ref: string | null, inputs: Record<string, string>): Promise<void> {
  await page.goto(ref === null ? "./#/run" : `./#/run/${encodeURIComponent(ref)}`);
  const form = page.getByTestId("pause-start");
  await expect(form).toBeVisible({ timeout: 30_000 });
  for (const [key, value] of Object.entries(inputs)) await fill(form, key, value);
  await page.getByTestId("pause-start-submit").click();
}

/** The pause form, once the run waits at `step`. */
export async function pausedAt(page: Page, step: string): Promise<Locator> {
  const form = page.locator(`[data-testid="pause-task"][data-step="${step}"]`);
  await expect(form).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("run-status")).toHaveText("paused");
  return form;
}

/** One task of a pause form, by its index. */
export const task = (form: Locator, index: number) => form.locator(`[data-testid="task"][data-index="${index}"]`);

export async function answer(form: Locator): Promise<void> {
  await form.getByTestId("answer").click();
}

export async function done(page: Page): Promise<void> {
  await expect(page.getByTestId("run-status")).toHaveText("done", { timeout: 30_000 });
}

/** The run's id, off the run page. */
export async function runIdOf(page: Page): Promise<string> {
  const id = (await page.getByTestId("run-id").textContent())!.trim();
  expect(id).toMatch(/^[0-9a-f]{16}$/);
  return id;
}

/** A step's entry in the record on the page; `nth` picks among the passes of a loop. */
export const entry = (page: Page | Locator, step: string, nth = 0) =>
  page.locator(`[data-testid="record-entry"][data-step="${step}"]`).nth(nth);

/** A card of the canvas, by its step's name. */
export const card = (page: Page | Locator, step: string) => page.locator(`[data-testid="canvas-card"][data-step="${step}"]`);
