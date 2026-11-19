import { expect, test } from "@playwright/test";
import { AGENT, BILLING, FIXED, resume, run } from "./aip";

// Audit: the server's named queries over the record and the catalog (aip docs/server-design.md, Audit),
// each shown as a list, with the queries' parameters as filters.

const ids: Record<string, string> = {};

test.beforeAll(() => {
  const who = { agent: "auditor", session: "audit-s1" };
  // A check that fires, and a loop that goes round twice because an aggregation did not hold.
  ids.fired = run(BILLING, { message: "Was that two charges? [calm] [unsure]" }, who).run_id as string;
  let paused = run(FIXED, { request: "A note." }, who);
  paused = resume(paused.run_id as string, { work: "Oi. [break:courteous]" }, who);
  ids.loop = resume(paused.run_id as string, { work: "Dear customer." }, who).run_id as string;
});

const query = (name: string) => `[data-testid="audit-query"][data-query="${name}"]`;

test("the built-in queries answer from the runs and the catalog", async ({ page }) => {
  await page.goto("./#/audit");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Audit");
  for (const name of ["confidence-fired", "failing-aggregations", "model-answers", "failing-scripts", "untaken-branches", "repeated-cycles",
                      "agent-routes", "missing-fields", "empty-results", "unused-data", "cycles"]) {
    await expect(page.locator(query(name))).toHaveAttribute("data-state", "rows", { timeout: 30_000 });
  }

  // The fired check, with the run it sent elsewhere one click away.
  const fired = page.locator(query("confidence-fired")).locator(`[data-testid="audit-row"][data-name="${BILLING}"][data-reason="below"]`);
  await expect(fired).toHaveAttribute("data-route", "by_tone");
  await expect(fired.getByTestId("run-ids")).toContainText(ids.fired);

  // The route an agent steers, off the graph: no run needed.
  await expect(page.locator(query("agent-routes")).locator(`[data-testid="audit-row"][data-name="${AGENT}"]`)).toContainText("by_tone");
  await expect(page.locator(query("failing-aggregations")).locator(`[data-testid="audit-row"][data-name="${FIXED}"]`)).toContainText("all_hold");

  // A query that cannot run without a parameter says which, and runs once it has it.
  const lineage = page.locator(query("lineage"));
  await expect(lineage).toHaveAttribute("data-state", "needs");
  await expect(lineage.getByTestId("needs")).toContainText("key");
  await page.getByTestId("audit-filters").getByLabel("procedure").selectOption(FIXED);
  await page.getByTestId("audit-filters").getByLabel("key", { exact: true }).fill("check_summary");
  await expect(lineage).toHaveAttribute("data-state", "rows", { timeout: 30_000 });
  await expect(lineage).toContainText("policy_check");
});

test("the filters are the queries' parameters: an agent nobody is leaves the run queries empty", async ({ page }) => {
  await page.goto("./#/audit");
  await expect(page.locator(query("confidence-fired")).getByTestId("audit-row").first()).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("audit-filters").getByLabel("agent", { exact: true }).fill("nobody-at-all");
  await expect(page.locator(query("confidence-fired")).getByTestId("no-rows")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(query("model-answers")).getByTestId("no-rows")).toBeVisible();
  // The catalog queries do not read runs: they still answer.
  await expect(page.locator(query("cycles")).getByTestId("audit-row").first()).toBeVisible();

  await page.getByTestId("audit-filters").getByLabel("agent", { exact: true }).fill("auditor");
  await expect(page.locator(query("confidence-fired")).getByTestId("run-ids")).toContainText(ids.fired);
});

test("a query of one's own is stored, listed, run and removed", async ({ page }) => {
  await page.goto("./#/audit");
  const form = page.getByTestId("add-query");
  await form.getByTestId("query-name").fill("runs-by-agent");
  await form.getByTestId("query-description").fill("How many runs each agent made.");
  await form.getByTestId("query-cypher").fill("MATCH (r:Run) RETURN r.agent AS agent, count(r) AS runs ORDER BY runs DESC, agent LIMIT $limit");
  await form.getByTestId("store-query").click();

  const stored = page.locator(query("runs-by-agent"));
  await expect(stored).toHaveAttribute("data-builtin", "false");
  await expect(stored.getByTestId("stored-tag")).toBeVisible();
  await expect(stored.getByTestId("audit-row").filter({ hasText: "auditor" })).toBeVisible({ timeout: 30_000 });

  // A statement that writes is refused when it is stored.
  await form.getByTestId("query-name").fill("sneaky");
  await form.getByTestId("query-cypher").fill("MATCH (r:Run) DETACH DELETE r");
  await form.getByTestId("store-query").click();
  await expect(form).toHaveAttribute("data-state", "error");
  await expect(form.getByRole("alert")).toContainText("invalid_request");

  await stored.getByTestId("remove-query").click();
  await expect(stored).toHaveCount(0);
});
