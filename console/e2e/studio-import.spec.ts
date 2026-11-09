import { expect, test, type Page } from "@playwright/test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { parse } from "yaml";
import { diffLines } from "../src/diff/lines";
import { FORMAT_VERSION } from "../src/studio/draft";
import { canUpgrade, carried, importSkill, versionMessage } from "../src/studio/import";
import { buildScaffold, NOTES_PATH, packScaffold, README_PATH } from "../src/studio/scaffold";
import { packSkill, unpackSkill, type ZipFile } from "../src/zip";
import { aip, FIRST_REVISION_DIR, SERVER } from "./aip";

// Import and draft management (S4): a skill comes into the Studio from the catalog or a zip, keeps every file it
// had, and goes back out with only what was edited changed. Several drafts live side by side in the browser.

/** A skill folder's files, as the zip and the catalog give them. */
function folderFiles(dir: string): ZipFile[] {
  const out: ZipFile[] = [];
  const walk = (rel: string) => {
    for (const item of readdirSync(path.join(dir, rel)).sort()) {
      const sub = rel ? `${rel}/${item}` : item;
      const st = statSync(path.join(dir, sub));
      if (st.isDirectory()) walk(sub);
      else out.push({ path: sub, bytes: new Uint8Array(readFileSync(path.join(dir, sub))), mode: st.mode & 0o777 });
    }
  };
  walk("");
  return out;
}

const text = (b: Uint8Array) => new TextDecoder().decode(b);
const body = (skillMd: string) => parse(/```yaml\n(.*?)\n```/s.exec(skillMd)![1]);
const changed = (a: string, b: string) => diffLines(a, b).filter((op) => op.kind !== "equal");

test("billing-support imports and exports without edits: the same files, the same SKILL.md", () => {
  const original = folderFiles(FIRST_REVISION_DIR);
  const draft = importSkill(original);
  const scaffold = buildScaffold(draft, carried(draft));
  expect(scaffold.issues.filter((i) => i.tier === "error")).toEqual([]);
  expect(scaffold.placeholders).toEqual([]);

  const out = new Map(unpackSkill(packScaffold(scaffold)).files.map((f) => [f.path, f]));
  // every file comes back with its bytes and mode, the skill's own source/README.md included; the Studio's notes sit beside it
  for (const f of original) {
    expect(out.get(f.path), f.path).toBeDefined();
    expect(Buffer.from(out.get(f.path)!.bytes).equals(Buffer.from(f.bytes)), f.path).toBe(true);
    expect(out.get(f.path)!.mode, f.path).toBe(f.mode);
  }
  expect([...out.keys()].filter((p) => !original.some((f) => f.path === p))).toEqual([NOTES_PATH]);

  // the YAML body is semantically equal (and, written into the original text, byte for byte the same)
  const before = text(original.find((f) => f.path === "SKILL.md")!.bytes);
  const after = text(out.get("SKILL.md")!.bytes);
  expect(body(after)).toEqual(body(before));
  expect(after).toBe(before);
});

test("an edit that adds or removes keys is written afresh, and still says what the draft says", () => {
  const draft = importSkill(folderFiles(FIRST_REVISION_DIR));
  const before = text(readFileSync(path.join(FIRST_REVISION_DIR, "SKILL.md")));
  draft.antiPatterns.pop();
  draft.steps.find((s) => s.name === "escalate")!.timeout = 30;
  const after = text(buildScaffold(draft, carried(draft)).files.find((f) => f.path === "SKILL.md")!.bytes);
  const expected = body(before);
  expected.anti_patterns.pop();
  expected.steps.find((s: { name: string }) => s.name === "escalate").timeout = 30;
  expect(body(after)).toEqual(expected);
});

test("an edit to folded prose replaces only that value, and the rest keeps its formatting", () => {
  const draft = importSkill(folderFiles(FIRST_REVISION_DIR));
  const before = text(readFileSync(path.join(FIRST_REVISION_DIR, "SKILL.md")));
  draft.purpose = "Turn a billing message into a ticket or a reply.\nTwo lines now.";
  const after = text(buildScaffold(draft, carried(draft)).files.find((f) => f.path === "SKILL.md")!.bytes);
  expect(body(after)).toEqual({ ...body(before), purpose: draft.purpose });
  const diff = changed(before, after);
  expect(diff.filter((op) => op.kind === "add")).toEqual([{ kind: "add", text: `purpose: ${JSON.stringify(draft.purpose)}`, b: expect.any(Number) }]);
  expect(diff.every((op) => op.kind === "add" || /^purpose:|^  /.test(op.text))).toBe(true);
});

test("a re-imported scaffold drops the Studio's own placeholders and notes, which the export makes again", () => {
  const draft = importSkill(folderFiles(FIRST_REVISION_DIR));
  draft.files = [];   // as if the skill had only its SKILL.md: every referenced file becomes a placeholder
  const scaffold = buildScaffold(draft);
  expect(scaffold.placeholders.length).toBeGreaterThan(0);
  const again = importSkill(unpackSkill(packScaffold(scaffold)).files);
  expect(again.files).toEqual([]);
  expect(buildScaffold(again, carried(again)).files.map((f) => f.path)).toEqual(scaffold.files.map((f) => f.path));
});

test("another format version gets aip-spec's own message, and the export stamps the current one", () => {
  expect(versionMessage(FORMAT_VERSION)).toBeNull();
  for (const v of ["0.5a1", "0.6a0", "0.6a1"]) {
    expect(versionMessage(v)).toContain("run `aip upgrade <folder>`");
    expect(versionMessage(v)).toContain(`Format 0.8 does not accept ${v} skills`);
    expect(canUpgrade(v)).toBe(true);
  }
  expect(canUpgrade("9.9")).toBe(false);
  expect(versionMessage("9.9")).toBe("`metadata.aip-version` is `9.9` but this validator implements `0.8`; update the skill or install a matching aip-spec version");
});

// ------------------------------------------------------------------------------------------------ the page

const nodeNamed = (page: Page, name: string) => page.getByRole("button", { name: new RegExp(`^${name} \\(`) });
const drafts = (page: Page) => page.getByTestId("studio-drafts");

async function exported(page: Page): Promise<Map<string, ZipFile>> {
  await page.getByTestId("studio-export").click();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-download").click()]);
  return new Map(unpackSkill(new Uint8Array(readFileSync(await download.path()))).files.map((f) => [f.path, f]));
}

test("proof: publish billing-support, import it into Studio from the catalog, edit one description, export: one line changed", async ({ page }) => {
  const published = aip(["publish", FIRST_REVISION_DIR]).trim();
  const ref = /billing-support@[0-9a-f]+/.exec(published)![0];

  await page.goto(`./#/p/${encodeURIComponent(ref)}`);
  await page.getByTestId("edit-in-studio").click();
  await expect(page.getByTestId("studio-notice")).toHaveText(`Imported ${ref} as a new draft.`);
  await expect(page).toHaveURL(/#\/studio$/);
  await expect(page.getByTestId("step-node")).toHaveCount(6);   // the start step is a node
  await expect(drafts(page).getByLabel("draft")).toHaveValue(/.+/);
  await expect(drafts(page).getByLabel("draft").locator("option:checked")).toHaveText(ref);
  // the skill's own scripts and templates came with it: nothing is a placeholder, nothing is an error
  await expect(page.getByTestId("lint-error")).toHaveCount(0);
  await expect(page.getByTestId("lint-panel").locator('li[data-code="placeholder_file"]')).toHaveCount(0);
  await expect(page.getByTestId("version-banner")).toHaveCount(0);

  await nodeNamed(page, "reply").click();
  const newText = "Draft a calm, short reply grounded in the refund policy.";
  await page.getByTestId("step-panel").locator('[data-field="description"]').fill(newText);
  const files = await exported(page);

  // the original, as the server holds it
  const manifest = (await (await fetch(`${SERVER}/catalog/${encodeURIComponent(ref)}/files`)).json()) as { path: string }[];
  const original = new Map<string, Uint8Array>();
  for (const f of manifest) {
    const res = await fetch(`${SERVER}/catalog/${encodeURIComponent(ref)}/files/${f.path.split("/").map(encodeURIComponent).join("/")}`);
    original.set(f.path, new Uint8Array(await res.arrayBuffer()));
  }
  const diff = changed(text(original.get("SKILL.md")!), text(files.get("SKILL.md")!.bytes));
  console.log(`proof: ${ref} imported from the catalog and exported with one description edited; SKILL.md diff:\n${diff.map((op) => `${op.kind === "add" ? "+" : "-"} ${op.text}`).join("\n")}`);
  expect(diff).toEqual([
    { kind: "remove", text: "    description: Draft a calm reply grounded in the refund policy.", a: expect.any(Number) },
    { kind: "add", text: `    description: ${newText}`, b: expect.any(Number) },
  ]);
  for (const [p, bytes] of original) {
    if (p === "SKILL.md") continue;
    expect(Buffer.from(files.get(p)!.bytes).equals(Buffer.from(bytes)), p).toBe(true);
  }
  expect([...files.keys()].filter((p) => !original.has(p))).toEqual([NOTES_PATH]);
  console.log(`proof: the other ${original.size - 1} files are byte for byte the same; the zip adds only ${NOTES_PATH}`);
});

test("a zip in another format version imports with aip-spec's message as a banner, and exports as 0.8", async ({ page }) => {
  const files = folderFiles(FIRST_REVISION_DIR).map((f) =>
    f.path === "SKILL.md" ? { ...f, bytes: new TextEncoder().encode(text(f.bytes).replace('aip-version: "0.8"', 'aip-version: "0.6a1"')) } : f);
  await page.goto("./#/studio");
  await drafts(page).getByLabel("import skill zip").setInputFiles({ name: "old.zip", mimeType: "application/zip", buffer: Buffer.from(packSkill("billing-support", files)) });
  await expect(page.getByTestId("studio-notice")).toHaveText("Imported old.zip as a new draft.");
  await expect(page.getByTestId("version-banner")).toContainText("Format 0.8 does not accept 0.6a1 skills");
  await expect(page.getByTestId("version-banner")).toContainText("The export stamps 0.8");
  const out = await exported(page);
  const md = text(out.get("SKILL.md")!.bytes);
  expect(md).toContain('aip-version: "0.8"');
  expect(changed(text(files.find((f) => f.path === "SKILL.md")!.bytes), md)).toHaveLength(2);

  // a zip that is not a skill is reported, and no draft is made
  const count = await drafts(page).getByLabel("draft").locator("option").count();
  await drafts(page).getByLabel("import skill zip").setInputFiles({ name: "junk.zip", mimeType: "application/zip", buffer: Buffer.from("not a zip") });
  await expect(page.getByTestId("studio-notice")).toContainText("Could not import junk.zip: not a zip file");
  await expect(drafts(page).getByLabel("draft").locator("option")).toHaveCount(count);
});

test("drafts: new, rename, switch, reset and delete, all kept across a reload", async ({ page }) => {
  await page.goto("./#/studio?new");
  await expect(page).toHaveURL(/#\/studio$/);
  const select = drafts(page).getByLabel("draft");
  const rename = async (name: string) => {
    await drafts(page).getByRole("button", { name: "rename" }).click();
    await drafts(page).getByLabel("draft name").fill(name);
    await drafts(page).getByRole("button", { name: "save name" }).click();
    await expect(select.locator("option:checked")).toHaveText(name);
  };
  // the first step brings the start step with it
  const addFirst = async (kind: string) => {
    await page.getByRole("group", { name: "Add the first step" }).getByRole("button", { name: `+ ${kind}` }).click();
    await expect(page.getByTestId("step-node")).toHaveCount(2);
  };

  await rename("alpha");
  await addFirst("decision");
  await drafts(page).getByRole("button", { name: "new draft" }).click();
  await expect(page.getByTestId("studio-empty")).toBeVisible();
  await rename("beta");
  await addFirst("execution");
  await page.getByRole("group", { name: /^Add step after execution-1/ }).getByRole("button", { name: "+ end" }).click();
  await expect(page.getByTestId("step-node")).toHaveCount(3);

  // switching shows each draft's own steps
  await select.selectOption({ label: "alpha" });
  await expect(page.getByTestId("step-node")).toHaveCount(2);
  await expect(page.getByTestId("step-node").last()).toHaveAttribute("data-kind", "decision");
  await select.selectOption({ label: "beta" });
  await expect(page.getByTestId("step-node")).toHaveCount(3);

  await expect(page.getByTestId("studio-saved")).toHaveAttribute("data-state", "saved");
  await page.reload();
  await expect(select.locator("option:checked")).toHaveText("beta");
  await expect(page.getByTestId("step-node")).toHaveCount(3);
  await expect(select.locator("option")).toContainText(["beta", "alpha"]);

  // reset asks first, then empties the open draft and keeps its name
  await drafts(page).getByRole("button", { name: "reset" }).click();
  await drafts(page).getByRole("group", { name: "confirm reset" }).getByRole("button", { name: "cancel" }).click();
  await expect(page.getByTestId("step-node")).toHaveCount(3);
  await drafts(page).getByRole("button", { name: "reset" }).click();
  await drafts(page).getByRole("button", { name: "yes, reset" }).click();
  await expect(page.getByTestId("studio-empty")).toBeVisible();
  await expect(select.locator("option:checked")).toHaveText("beta");

  // delete asks first, then removes the draft and opens another
  await drafts(page).getByRole("button", { name: "delete draft" }).click();
  await drafts(page).getByRole("button", { name: "yes, delete" }).click();
  await expect(select.locator("option")).not.toContainText(["beta"]);
  await expect(select.locator("option:checked")).not.toHaveText("beta");
  await page.reload();
  await expect(select.locator("option")).not.toContainText(["beta"]);
});

test("without storage the page says drafts will not be kept, and still works", async ({ page }) => {
  await page.addInitScript(() => {
    const fail = () => { throw new DOMException("blocked", "SecurityError"); };
    Object.defineProperty(globalThis, "localStorage", { get: () => ({ getItem: fail, setItem: fail, removeItem: fail }) });
  });
  await page.goto("./#/studio");
  await expect(page.getByTestId("storage-notice")).toBeVisible();
  await page.getByRole("group", { name: "Add the first step" }).getByRole("button", { name: "+ decision" }).click();
  await expect(page.getByTestId("step-node")).toHaveCount(2);
});

test("the catalog links to a new draft in the Studio", async ({ page }) => {
  await page.goto("./");
  await page.getByTestId("new-in-studio").click();
  await expect(page).toHaveURL(/#\/studio$/);
  await expect(page.getByTestId("studio-empty")).toBeVisible();
});
