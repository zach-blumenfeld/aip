import { expect, test, type APIRequestContext } from "@playwright/test";
import { CHECKED, SERVER as BASE } from "./aip";

// Governance: pin and retire from the procedure page (publish scope; the e2e server is open on
// localhost), and the corpus queries of GET /governance as lists.
//
// The e2e CLI has no decision model, so every decision the other specs drive is answered by hand,
// which records no confidence. One run of billing-checked (the example as shipped, whose router
// checks `tone_confidence` below 0.6) with a model-answered triage is posted straight to the run
// API, the way a client with a model reports it: the model said `calm` with confidence 0.55, so
// the router's check fires with reason `low` and the run escalates all the same.

interface Entry { name: string; pinned: string | null; latest: string; revisions: { revision: string; retired: boolean }[] }

async function entry(request: APIRequestContext): Promise<Entry> {
  const res = await request.get(`${BASE}/catalog`);
  expect(res.ok()).toBeTruthy();
  const found = ((await res.json()) as Entry[]).find((e) => e.name === "billing-support");
  expect(found).toBeDefined();
  return found!;
}

test.describe.configure({ mode: "serial" });

test("pin a revision; the pin survives a reload", async ({ page, request }) => {
  // Start clean, whatever an earlier spec left.
  expect((await request.post(`${BASE}/catalog/billing-support/pin`, { data: { revision: null } })).ok()).toBeTruthy();
  const latest = (await entry(request)).latest;

  await page.goto("./#/p/billing-support");
  const box = page.getByTestId("governance");
  await expect(box).toBeVisible();
  await expect(box.getByTestId("pin-state")).toHaveText("no pin");
  await box.getByRole("button", { name: "Pin this revision" }).click();
  await expect(box.getByTestId("governance-note")).toContainText("Pinned");
  await expect(box.getByTestId("pin-state")).toContainText(`pinned ${latest.slice(0, 8)} (this revision)`);
  await expect(box.getByRole("button", { name: "Pin this revision" })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "revision" })).toContainText("pinned");
  // The router's check and the decision's fallback are the author's: shown on the step cards, with nothing to override.
  await expect(page.locator("#step-triage").getByTestId("fallback")).toHaveAttribute("data-fallback", "true");
  await expect(page.getByLabel("override for tone")).toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId("pin-state")).toContainText(`pinned ${latest.slice(0, 8)} (this revision)`);
  expect((await entry(request)).pinned).toBe(latest);

  // The pinned revision is the latest one, so the bare name still resolves as before for the other specs.
  await page.getByTestId("governance").getByRole("button", { name: "Unpin" }).click();
  await expect(page.getByTestId("pin-state")).toHaveText("no pin");
  expect((await entry(request)).pinned).toBeNull();
});

test("retire the older revision from its page; the name still resolves to the latest", async ({ page, request }) => {
  const before = await entry(request);
  const older = before.revisions.find((r) => r.revision !== before.latest)!;
  expect(older).toBeDefined();

  await page.goto(`./#/p/billing-support@${older.revision}`);
  const box = page.getByTestId("governance");
  await expect(box).toBeVisible();
  if (!older.retired) {                                   // a reused root has already retired it
    await box.getByRole("button", { name: "Retire this revision…" }).click();
    await expect(box).toContainText("This cannot be undone");
    await box.getByRole("button", { name: "Cancel" }).click();
    await expect(box.getByTestId("retired-state")).toHaveCount(0);
    await box.getByRole("button", { name: "Retire this revision…" }).click();
    await box.getByRole("button", { name: "Confirm retire" }).click();
    await expect(box.getByTestId("governance-note")).toContainText("Retired");
  }
  await expect(box.getByTestId("retired-state")).toHaveText("This revision is retired.");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("(retired)");
  await expect(page.getByRole("combobox", { name: "revision" })).toContainText("retired");
  await expect(box.getByRole("button", { name: "Pin this revision" })).toHaveCount(0);

  const after = await entry(request);
  expect(after.revisions.find((r) => r.revision === older.revision)!.retired).toBe(true);
  expect(after.latest).toBe(before.latest);
  const resolved = await (await request.get(`${BASE}/catalog/billing-support`)).json();
  expect(resolved.revision).toBe(before.latest);
});

test("the governance page lists the fired check and the unmeasured route, and marks the graph-only query", async ({ page, request }) => {
  const message = "Hi, could you tell me why I was billed $12 this month? [governance]";
  const opened = await request.post(`${BASE}/runs`, { data: { name: CHECKED, input: { message } } });
  expect(opened.status(), await opened.text()).toBe(201);
  const { run_id: runId } = (await opened.json()) as { run_id: string };
  const answered = await request.post(`${BASE}/runs/${runId}/result`, { data: {
    step: "triage",
    answer: { billing: true, tone: "calm" },
    attribution: { resolver: "typesafe", model: "jev-1", confidence: { billing: 0.97, tone: 0.55 } },
  } });
  expect(answered.ok(), await answered.text()).toBeTruthy();
  // 0.55 is below the router's bound: the check fired and sent the run to escalate, not reply. The router's entry is
  // written with the step after it, so the client reports the script's result as if it had run it.
  const paused = (await (await request.get(`${BASE}/runs/${runId}`)).json()) as { pause: { kind: string; step: string } };
  expect(paused.pause).toMatchObject({ kind: "execute", step: "escalate" });
  const reported = await request.post(`${BASE}/runs/${runId}/result`, { data: { step: "escalate", answer: { output: { ticket_id: 55, queue: "tier2" }, seconds: 0.2 } } });
  expect(reported.ok(), await reported.text()).toBeTruthy();
  const after = (await (await request.get(`${BASE}/runs/${runId}`)).json()) as { status: string; history: { step: string; result: Record<string, unknown> }[] };
  expect(after.status).toBe("done");
  expect(after.history.map((h) => h.step)).toEqual(["start", "triage", "by-tone", "escalate", "end"]);
  expect(after.history.find((h) => h.step === "by-tone")!.result).toMatchObject({ to: "escalate", confidence: { fired: true, reason: "low" } });

  // The run page says what the check did.
  await page.goto(`./#/runs/${runId}`);
  const route = page.locator('[data-testid="run-step"][data-step="by-tone"]');
  await expect(route.getByTestId("check-outcome")).toHaveAttribute("data-fired", "true");
  await expect(route.getByTestId("check-outcome")).toHaveAttribute("data-reason", "low");
  await expect(route.getByTestId("check-outcome")).toContainText("tone_confidence");
  await expect(route.getByTestId("branch-taken")).toContainText("the check sent the run to escalate");
  const triage = page.locator('[data-testid="run-step"][data-step="triage"]');
  await expect(triage.locator('[data-question="tone"] [data-testid="answer-confidence"]')).toHaveText("0.550");
  expect(JSON.parse(await triage.getByTestId("state-out").innerText())).toEqual({ billing: true, tone: "calm", tone_confidence: 0.55 });

  await page.goto("./#/governance");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Governance");
  const queries = page.getByTestId("governance-query");
  await expect(queries).toHaveCount(10);
  for (const q of ["confidence-fired", "unmeasured-routes", "manual-decisions", "failing-scripts", "missing-fields", "untaken-branches",
                   "empty-results", "unused-data", "cycles", "repeated-cycles"]) {
    await expect(page.locator(`[data-testid="governance-query"][data-query="${q}"]`)).toHaveCount(1);
  }

  const fired = page.locator('[data-testid="governance-query"][data-query="confidence-fired"]');
  await expect(fired).toHaveAttribute("data-state", "rows");
  const row = fired.locator(`[data-testid="governance-row"][data-name="${CHECKED}"][data-router="by-tone"][data-reason="low"]`);
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("link", { name: CHECKED })).toHaveAttribute("href", new RegExp(`#/p/${CHECKED}$`));
  await expect(row.getByTestId("run-ids").getByRole("link", { name: runId })).toHaveAttribute("href", new RegExp(`#/runs/${runId}$`));
  // billing-support's router has no check in the e2e revisions, so it never fires
  await expect(fired.locator('[data-testid="governance-row"][data-name="billing-support"]')).toHaveCount(0);

  // The validator flagged both routers at publish: billing-checked's check reads a confidence a by-hand answer never
  // writes; billing-support's e2e revision has no check at all.
  const unmeasured = page.locator('[data-testid="governance-query"][data-query="unmeasured-routes"]');
  await expect(unmeasured).toHaveAttribute("data-state", "rows");
  const checkedRow = unmeasured.locator(`[data-testid="governance-row"][data-name="${CHECKED}"][data-router="by-tone"]`);
  await expect(checkedRow).toHaveAttribute("data-code", "confidence_on_unmeasured_source");
  await expect(checkedRow.getByTestId("source-class")).toHaveText("unmeasured");
  await expect(unmeasured.locator('[data-testid="governance-row"][data-name="billing-support"][data-router="by-tone"]')).toHaveAttribute("data-code", "unmeasured_route");

  // The filesystem backend scans run files for the others and declines the graph one.
  await expect(page.locator('[data-testid="governance-query"][data-query="failing-scripts"]')).toHaveAttribute("data-state", "rows");
  await expect(page.locator('[data-testid="governance-query"][data-query="missing-fields"] [data-testid="no-rows"]')).toBeVisible();
  const untaken = page.locator('[data-testid="governance-query"][data-query="untaken-branches"]');
  await expect(untaken).toHaveAttribute("data-state", "unsupported");
  await expect(untaken.getByTestId("needs-graph")).toContainText("needs the Neo4j backend");
  for (const q of ["empty-results", "unused-data", "cycles", "repeated-cycles"]) {
    await expect(page.locator(`[data-testid="governance-query"][data-query="${q}"]`)).toHaveAttribute("data-state", "unsupported");
  }
  // every listed query is a built-in here, so none offers removal
  await expect(page.locator('[data-testid="governance-query"][data-builtin="false"]')).toHaveCount(0);
  await expect(page.getByTestId("remove-query")).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);

  // The name filter rides in the hash and narrows every list.
  await page.getByRole("combobox", { name: "name" }).selectOption(CHECKED);
  await expect(page).toHaveURL(new RegExp(`#/governance\\?name=${CHECKED}$`));
  await expect(row).toHaveCount(1);
  await expect(unmeasured.locator('[data-testid="governance-row"][data-name="billing-support"]')).toHaveCount(0);

  // The server page shows the console's server and keeps a token for this browser; the token never reaches localStorage.
  await page.goto("./#/server");
  await expect(page.getByTestId("server-url")).toHaveText(BASE);
  await page.getByLabel("bearer token").fill("secret-token");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("server-note")).toContainText("procedure");
  expect(await page.evaluate(() => [localStorage.getItem("aip.token"), sessionStorage.getItem("aip.token")])).toEqual([null, "secret-token"]);
  await page.getByRole("button", { name: "Clear" }).click();
  expect(await page.evaluate(() => sessionStorage.getItem("aip.token"))).toBeNull();
});

test("keeping a query of your own needs the graph backend", async ({ page }) => {
  await page.goto("#/governance");
  const form = page.getByTestId("add-query");
  await expect(form).toBeVisible();
  await expect(page.getByTestId("store-query")).toBeDisabled();
  await page.getByTestId("query-name").fill("steps-by-kind");
  await page.getByTestId("query-cypher").fill("MATCH (st:Step) RETURN st.kind AS kind, count(*) AS steps");
  await expect(page.getByTestId("store-query")).toBeEnabled();
  await page.getByTestId("store-query").click();
  await expect(form).toHaveAttribute("data-state", "unsupported");
  await expect(form.getByTestId("needs-graph")).toContainText("needs the Neo4j backend");
});
