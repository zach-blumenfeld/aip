import { expect, test, type Page } from "@playwright/test";
import { strToU8, unzipSync, zipSync, type Zippable } from "fflate";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { aipJson, FIRST_REVISION_DIR, SECOND_REVISION_DIR, SERVER } from "./aip";

// Skill zips: a revision downloads as `<name>@<rev>.zip` holding `<name>/<path>` for every file of its
// manifest, and a zip of a skill folder publishes through the catalog page, where the server names the skill
// from SKILL.md's frontmatter: a new name appears, the same bytes land on the revision already there, and a
// change makes the next revision. The uploads use their own name so the other specs' two revisions of
// billing-support stay what they are.

const NAME = "zip-support";

interface Entry { path: string; size: number; sha256: string; mode: number }

/** The files of a skill folder, as `<name>/<path>` zip entries, with `edit` applied to SKILL.md and the rest. */
function zipOf(dir: string, name: string, edit: (path: string, text: string) => string | null = (_, t) => t): Buffer {
  const entries: Zippable = {};
  const walk = (rel: string) => {
    for (const item of readdirSync(path.join(dir, rel)).sort()) {
      const sub = rel ? `${rel}/${item}` : item;
      if (statSync(path.join(dir, sub)).isDirectory()) { walk(sub); continue; }
      const edited = edit(sub, readFileSync(path.join(dir, sub), "utf8"));
      if (edited !== null) entries[`${name}/${sub}`] = strToU8(edited);
    }
  };
  walk("");
  return Buffer.from(zipSync(entries));
}

/** billing-support's second revision renamed, so it publishes under NAME. */
const rename = (p: string, text: string) => (p === "SKILL.md" ? text.replace(/^name: billing-support$/m, `name: ${NAME}`) : text);

async function manifest(ref: string): Promise<Entry[]> {
  return (await (await fetch(`${SERVER}/catalog/${encodeURIComponent(ref)}/files`)).json()) as Entry[];
}

async function upload(page: Page, zip: Buffer, filename: string) {
  await page.getByLabel("skill zip").setInputFiles({ name: filename, mimeType: "application/zip", buffer: zip });
}

async function downloaded(page: Page): Promise<{ filename: string; entries: Record<string, Uint8Array> }> {
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-zip").click()]);
  const file = await download.path();
  return { filename: download.suggestedFilename(), entries: unzipSync(new Uint8Array(readFileSync(file))) };
}

test("the procedure page downloads the revision as a zip of its manifest", async ({ page }) => {
  await page.goto("./#/p/billing-support");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("@");
  const revision = /@([0-9a-f]{16})/.exec(await page.getByRole("heading", { level: 1 }).innerText())![1];

  const { filename, entries } = await downloaded(page);
  expect(filename).toBe(`billing-support@${revision}.zip`);
  const files = await manifest(`billing-support@${revision}`);
  expect(Object.keys(entries).filter((k) => !k.endsWith("/")).sort()).toEqual(files.map((f) => `billing-support/${f.path}`).sort());
  for (const f of files) {
    expect(createHash("sha256").update(entries[`billing-support/${f.path}`]).digest("hex"), f.path).toBe(f.sha256);
  }
});

test("a zip of a skill folder publishes from the catalog page and opens the new revision", async ({ page }) => {
  await page.goto("./");
  await upload(page, zipOf(SECOND_REVISION_DIR, NAME, rename), `${NAME}.zip`);
  await expect(page).toHaveURL(new RegExp(`#/p/${NAME}(%40|@)[0-9a-f]{16}$`));
  await expect(page.getByRole("heading", { level: 1 })).toContainText(NAME);
  const note = page.getByTestId("published-note");
  await expect(note).toHaveAttribute("data-existed", "false");
  await expect(note).toContainText(`Published ${NAME}.zip as this revision.`);

  await page.goto("./");
  const row = page.getByRole("table", { name: "catalog" }).getByRole("row").filter({ hasText: NAME });
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("cell").nth(3)).toHaveText("1");
});

test("the same zip again lands on the revision already there; a change makes the next one", async ({ page }) => {
  await page.goto("./");
  await upload(page, zipOf(SECOND_REVISION_DIR, NAME, rename), "again.zip");
  await expect(page.getByTestId("published-note")).toHaveAttribute("data-existed", "true");
  await expect(page.getByTestId("published-note")).toContainText("nothing changed");
  const first = /@([0-9a-f]{16})/.exec(decodeURIComponent(page.url()))![1];

  await page.goto("./");
  const changed = (p: string, text: string) => (p === "assets/policy.md" ? `${text}\n- Zip uploads are refunded in full.\n` : rename(p, text));
  await upload(page, zipOf(SECOND_REVISION_DIR, NAME, changed), "v2.zip");
  await expect(page.getByTestId("published-note")).toHaveAttribute("data-existed", "false");
  const second = /@([0-9a-f]{16})/.exec(decodeURIComponent(page.url()))![1];
  expect(second).not.toBe(first);
  await expect(page.getByRole("combobox", { name: "revision" })).toContainText("latest");
  await page.getByRole("link", { name: "diff with previous" }).click();
  await expect(page.getByTestId("diff-summary")).toContainText("1 changed");
});

test("a downloaded zip uploads back onto the same revision", async ({ page }) => {
  await page.goto(`./#/p/${NAME}/files`);
  const { filename, entries } = await downloaded(page);
  expect(filename).toMatch(new RegExp(`^${NAME}@[0-9a-f]{16}\\.zip$`));
  const revision = /@([0-9a-f]{16})/.exec(filename)![1];
  expect(Object.keys(entries)).toContain(`${NAME}/SKILL.md`);

  await page.goto("./");
  await upload(page, Buffer.from(zipSync(entries)), filename);
  await expect(page).toHaveURL(new RegExp(`#/p/${NAME}(%40|@)${revision}$`));
  await expect(page.getByTestId("published-note")).toHaveAttribute("data-existed", "true");
});

test("a zip that is not a skill is refused with the reason", async ({ page }) => {
  await page.goto("./");
  // No SKILL.md anywhere: the page says so before anything is sent.
  await upload(page, Buffer.from(zipSync({ "notes/readme.md": strToU8("# nothing here\n") })), "notes.zip");
  const error = page.getByTestId("upload-error");
  await expect(error).toContainText("no SKILL.md");
  await expect(page).toHaveURL(/#\/$|\/$/);

  // A skill the server rejects: the validator's issues are listed. Without source/ the folder structure fails.
  const noSource = (p: string, text: string) => (p.startsWith("source/") ? null : rename(p, text).replace(`name: ${NAME}`, "name: zip-broken"));
  await upload(page, zipOf(SECOND_REVISION_DIR, "zip-broken", noSource), "broken.zip");
  await expect(error).toContainText("invalid_skill");
  await expect(error.getByTestId("issues").getByRole("listitem").first()).toContainText("source");
  await expect(page.getByRole("table", { name: "catalog" }).getByRole("row").filter({ hasText: "zip-broken" })).toHaveCount(0);
});

test("run traffic weights the graph's edges by the runs that took them", async ({ page }) => {
  // The uploaded skill has no runs yet, so its traffic is exactly what this test drives: two runs, one through
  // escalate to the end, one paused at reply (an answer is never given), both answered by hand at triage.
  for (const tone of ["angry", "calm"] as const) {
    const paused = aipJson(["run", NAME], { message: tone === "angry" ? "Charged twice, furious." : "Could I get a receipt?" });
    expect(paused.paused).toBe("decision");
    aipJson(["resume", paused.run_id as string], { billing: true, tone });
  }
  await page.goto(`./#/p/${NAME}`);
  await page.getByLabel("run traffic").check();
  const summary = page.getByTestId("traffic-summary");
  await expect(summary).toHaveAttribute("data-runs", "2");
  await expect(summary).toContainText("1 done, 1 paused");

  const graph = page.getByRole("img", { name: "step graph" });
  const edge = (from: string, to: string) => graph.locator(`[data-testid="step-edge"][data-from="${from}"][data-to="${to}"]`);
  await expect(edge("triage", "by-tone")).toHaveAttribute("data-runs", "2");
  await expect(edge("by-tone", "escalate")).toHaveAttribute("data-runs", "1");
  await expect(edge("escalate", "end")).toHaveAttribute("data-runs", "1");
  await expect(edge("by-tone", "reply")).toHaveAttribute("data-runs", "1");
  await expect(edge("reply", "end")).toHaveAttribute("data-runs", "0");
  const badge = (step: string) => graph.locator(`[data-testid="step-node"][data-step="${step}"] [data-testid="step-runs"]`);
  await expect(badge("triage")).toHaveAttribute("data-runs", "2");
  await expect(badge("reply")).toHaveAttribute("data-runs", "1");
  await expect(badge("end")).toHaveAttribute("data-runs", "1");
  await expect(page.locator('[data-testid="traffic-row"][data-step="end"]')).toHaveAttribute("data-runs", "1");

  // The other two modes are untouched by it.
  await page.getByLabel("control flow").check();
  await expect(graph.locator('[data-testid="edge-runs"]')).toHaveCount(0);

  // Both runs were on the latest revision. The one before shares its start and end, but its traffic is its own:
  // nothing, with the two runs named as left out.
  const revisions = page.getByRole("combobox", { name: "revision" });
  const older = (await revisions.locator("option").nth(1).getAttribute("value"))!;
  await revisions.selectOption(older);
  await expect(page).toHaveURL(new RegExp(`#/p/${NAME}(%40|@)${older}$`));
  await page.getByLabel("run traffic").check();
  await expect(summary).toHaveAttribute("data-runs", "0");
  await expect(summary).toContainText("2 runs of this name on other revisions are not counted");
  await expect(graph.locator('[data-testid="step-node"][data-step="end"] [data-testid="step-runs"]')).toHaveAttribute("data-runs", "0");
});

// billing-support's first revision with a policy check after the reply and a rewrite that loops back to it.
const LOOP = "zip-loop";
const LOOP_STEPS = `
  - name: check
    kind: decision
    description: Does the latest reply follow the refund policy?
    inputs:
      - name: message
        type: string
    history: true
    questions:
      ok:
        type: noul
        instructions: Does the latest reply in the run follow the refund policy?
    inputs_to: by-check

  - name: by-check
    kind: router
    description: A passing reply ends the run; otherwise rewrite it.
    branch_on: ok
    branches:
      "true": end
      "false": rewrite

  - name: rewrite
    kind: client_task
    description: Rewrite the reply so it follows the policy; the check runs again on the result.
    inputs:
      - name: message
        type: string
      - name: reply
        type: string
    template: assets/reply.md
    assets:
      - assets/policy.md
    outputs:
      - name: revised_reply
        type: string
        description: The rewritten reply.
    inputs_to: check
`;
const looped = (p: string, text: string) => {
  if (p !== "SKILL.md") return text;
  const tail = "        description: The drafted reply to send the customer.\n    inputs_to: end\n";
  expect(text).toContain(tail);
  return text.replace(/^name: billing-support$/m, `name: ${LOOP}`).replace(tail, tail.replace("inputs_to: end", "inputs_to: check") + LOOP_STEPS);
};

// The e2e tsconfig has no DOM types: what the page-side reader touches of an element.
interface El { getAttribute(name: string): string | null; querySelector(s: string): El | null; querySelectorAll(s: string): ArrayLike<El>; dataset: Record<string, string | undefined> }

/** Read in the page: every control edge's points against the drawing box and the other steps' boxes. */
const geometry = (svg: El) => {
  const [vx, vy, vw, vh] = svg.getAttribute("viewBox")!.split(" ").map(Number);
  const nodes = Array.from(svg.querySelectorAll('[data-testid="step-node"]')).map((n) => {
    const m = /translate\(([-\d.]+), ([-\d.]+)\)/.exec(n.getAttribute("transform")!)!;
    return { id: n.dataset.step!, x: Number(m[1]), y: Number(m[2]) };
  });
  const outside = new Set<string>(), through = new Set<string>();
  for (const e of Array.from(svg.querySelectorAll('[data-testid="step-edge"]'))) {
    const key = `${e.dataset.from}->${e.dataset.to}`;
    const pts = e.querySelector("path")!.getAttribute("d")!.match(/[-\d.]+ [-\d.]+/g)!.map((s: string) => s.split(" ").map(Number));
    for (const [x, y] of pts) if (x < vx || y < vy || x > vx + vw || y > vy + vh) outside.add(key);
    for (let i = 1; i < pts.length; i++) {
      for (let t = 0.01; t < 1; t += 0.01) {
        const x = pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0]), y = pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1]);
        for (const n of nodes) {
          if (n.id === e.dataset.from || n.id === e.dataset.to) continue;
          if (x > n.x + 1 && x < n.x + 149 && y > n.y + 1 && y < n.y + 47) through.add(`${key} through ${n.id}`);
        }
      }
    }
  }
  const at = Object.fromEntries(nodes.map((n) => [n.id, n]));
  return { outside: [...outside], through: [...through], at };
};

test("a loop runs on a rail outside the steps, and the graph draws left to right on request", async ({ page }) => {
  await page.goto("./");
  await upload(page, zipOf(FIRST_REVISION_DIR, LOOP, looped), "loop.zip");
  await expect(page.getByTestId("published-note")).toHaveAttribute("data-existed", "false");
  const graph = page.getByRole("img", { name: "step graph" });
  await expect(graph.locator('[data-testid="step-edge"][data-from="rewrite"][data-to="check"]')).toHaveCount(1);
  const clean = async () => {
    const g = await graph.evaluate(geometry);
    expect(g.outside).toEqual([]);
    expect(g.through).toEqual([]);
    return g.at;
  };

  // Top-down: layers go down the page, and the loop's rail stays inside the drawing and clear of every step.
  await expect(graph).toHaveAttribute("data-direction", "down");
  let at = await clean();
  expect(at.triage.y).toBeLessThan(at["by-tone"].y);
  expect(at.rewrite.y).toBeGreaterThan(at.check.y);

  // Left to right: the same layers go across; every mode keeps its edges clear.
  await page.getByLabel("left to right").check();
  await expect(graph).toHaveAttribute("data-direction", "right");
  at = await clean();
  expect(at.triage.x).toBeLessThan(at["by-tone"].x);
  expect(at["by-tone"].x).toBeLessThan(at.reply.x);
  expect(at.rewrite.x).toBeGreaterThan(at.check.x);
  await page.getByLabel("data flow").check();
  await expect(graph.getByTestId("data-edge").first()).toBeVisible();
  await clean();
  await page.getByLabel("run traffic").check();
  await expect(page.getByTestId("traffic-summary")).toHaveAttribute("data-runs", "0");
  await clean();

  // The choice is remembered: after a reload, and on the run page, which offers the same toggle.
  await page.reload();
  await expect(graph).toHaveAttribute("data-direction", "right");
  const runs = await (await fetch(`${SERVER}/runs?name=${NAME}&limit=1`)).json() as { run_id: string }[] | { runs: { run_id: string }[] };
  const run = (Array.isArray(runs) ? runs : runs.runs)[0];
  await page.goto(`./#/runs/${run.run_id}`);
  await expect(graph).toHaveAttribute("data-direction", "right");
  await clean();
  await page.getByLabel("left to right").uncheck();
  await expect(graph).toHaveAttribute("data-direction", "down");
  await page.reload();
  await expect(graph).toHaveAttribute("data-direction", "down");
});

test("a name whose every revision is retired is hidden from the catalog unless asked for, and cannot be run", async ({ page, request }) => {
  const entry = (await (await fetch(`${SERVER}/catalog`)).json() as { name: string; revisions: { revision: string }[] }[]).find((e) => e.name === NAME)!;
  for (const r of entry.revisions) {
    expect((await request.post(`${SERVER}/catalog/${NAME}/retire`, { data: { revision: r.revision } })).ok()).toBeTruthy();
  }
  // Hidden from the catalog by default, then listed last and marked when asked for.
  await page.goto("./");
  const table = page.getByRole("table", { name: "catalog" });
  const row = table.getByRole("row").filter({ hasText: NAME });
  await expect(table.getByRole("row").filter({ hasText: "billing-support" })).toHaveCount(1);
  await expect(row).toHaveCount(0);
  await page.getByRole("checkbox", { name: /show 1 name with every revision retired/ }).check();
  await expect(row).toHaveCount(1);
  await expect(row.getByTestId("all-retired")).toHaveText("all retired");
  await expect(table.locator("tbody tr").last()).toContainText(NAME);

  await page.goto("./#/run");
  await expect(page.getByRole("list").getByText(NAME)).toBeVisible();
  await expect(page.getByRole("link", { name: NAME })).toHaveCount(0);
  await expect(page.getByText("every revision is retired")).toBeVisible();
});
