import { expect, test } from "@playwright/test";
import { AGENT, BILLING, DRAFT_DIR, DYNAMIC, FIXED, TRIAGE, run } from "./aip";

// The catalog: what is published, searchable by what a procedure does; drafts are kept out of it.

const row = (name: string) => `[data-testid="catalog-row"][data-name="${name}"]`;

test("the catalog lists the published names and the revision each runs as", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByTestId("console-target")).toContainText("http://localhost:");
  await expect(page.locator(".top-nav").getByRole("link")).toHaveText(["catalog", "studio", "run", "history", "audit"]);
  for (const name of [AGENT, BILLING, DYNAMIC, FIXED, TRIAGE]) await expect(page.locator(row(name))).toBeVisible();
  await expect(page.locator(row(AGENT))).toContainText("@2");
  await expect(page.locator(row(BILLING))).toContainText("@1");
  await page.locator(row(FIXED)).getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(FIXED);
});

test("search ranks by what a procedure does", async ({ page }) => {
  await page.goto("./");
  await page.getByLabel("search").fill("policies the requester supplies");
  const results = page.getByRole("table", { name: "search results" });
  await expect(results.getByRole("row").nth(1)).toContainText(DYNAMIC);
  await page.getByLabel("search", { exact: true }).fill("zebra crossing");
  await expect(page.getByText("No procedure matches")).toBeVisible();
});

test("a draft is not in the catalog; the toggle lists it apart, with its runs", async ({ page }) => {
  run(DRAFT_DIR, { message: "A folder nobody published." });
  await page.goto("./");
  // The five the harness published, and the four built-ins every server publishes when it first starts.
  await expect(page.locator('[data-testid="catalog-row"]')).toHaveCount(9);
  for (const builtin of ["make_procedure", "build_procedure", "edit_procedure", "assist"]) {
    await expect(page.locator(row(builtin))).toContainText("@1");
  }
  await expect(page.getByTestId("drafts")).toHaveCount(0);

  await page.getByTestId("show-drafts").check();
  const draft = page.locator(`[data-testid="draft-row"][data-name="${AGENT}"]`);
  await expect(draft).toHaveCount(1);
  await expect(draft.getByTestId("draft-badge")).toBeVisible();
  await draft.getByRole("link", { name: "runs" }).click();
  await expect(page).toHaveURL(new RegExp(`#/runs\\?name=${AGENT}&draft=true$`));
  await expect(page.locator('[data-testid="run-row"][data-draft="true"]').first()).toBeVisible();
  await expect(page.locator('[data-testid="run-row"][data-draft="false"]')).toHaveCount(0);
});
