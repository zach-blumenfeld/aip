import { expect, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { Draft } from "../src/studio/draft";
import { PLACEHOLDER_MARKER } from "../src/studio/lint";
import { buildScaffold, packScaffold, README_PATH } from "../src/studio/scaffold";
import { skillMdToDraft } from "../src/studio/serialize";
import { unpackSkill } from "../src/zip";
import { AIP_REPO, FIRST_REVISION_DIR } from "./aip";
import { aipSpec, specErrors } from "./aip-spec";

// The scaffold against the real validator (S3): a complete draft's scaffold passes `aip-spec validate` with every
// referenced file present, so `missing_resource` cannot occur; a draft with errors fails it with a code the
// linter also reports. The Python stub runs and prints exactly the declared outputs with their types.

const billing = (): Draft => skillMdToDraft(readFileSync(path.join(FIRST_REVISION_DIR, "SKILL.md"), "utf8"));

/** The scaffold zipped, unzipped with unpackSkill, and written to `<root>/<name>/`. */
function writeOut(root: string, draft: Draft): { dir: string; files: Map<string, string> } {
  const scaffold = buildScaffold(draft);
  const { files, folder } = unpackSkill(packScaffold(scaffold));
  expect(folder).toBe(scaffold.name);
  const dir = path.join(root, scaffold.name);
  for (const f of files) {
    mkdirSync(path.dirname(path.join(dir, f.path)), { recursive: true });
    writeFileSync(path.join(dir, f.path), f.bytes, { mode: f.mode });
  }
  return { dir, files: new Map(files.map((f) => [f.path, new TextDecoder().decode(f.bytes)])) };
}

function runStub(script: string, stdin: object): unknown {
  const run = spawnSync("uv", ["run", "--quiet", "--project", AIP_REPO, "python", script], { input: JSON.stringify(stdin), encoding: "utf8" });
  expect(run.status, run.stderr).toBe(0);
  return JSON.parse(run.stdout);
}

test.beforeEach(() => {
  test.skip(aipSpec(["--version"]).status !== 0, "aip-spec is not available (needs uv and the aip repo's environment)");
});

test("a complete draft's scaffold passes aip-spec validate, with every referenced file present", () => {
  const root = mkdtempSync(path.join(tmpdir(), "studio-scaffold-"));
  try {
    const draft = billing();
    const scaffold = buildScaffold(draft);
    // complete: no errors, and nothing unfinished but the placeholders themselves
    expect(scaffold.issues.filter((i) => i.tier === "error")).toEqual([]);
    expect(new Set(scaffold.issues.filter((i) => i.tier === "unfinished").map((i) => i.code))).toEqual(new Set(["placeholder_file"]));

    const { dir, files } = writeOut(root, draft);
    expect([...files.keys()].sort()).toEqual([
      "SKILL.md", "assets/config.json", "assets/policy.md", "assets/reply.md", README_PATH, "references/help.md", "scripts/escalate.py",
    ].sort());
    for (const [p, text] of files) if (p !== "SKILL.md" && p !== README_PATH) expect(text, p).toContain(PLACEHOLDER_MARKER);
    expect(files.get(README_PATH)).not.toContain("DRAFT:");
    expect(files.get(README_PATH)).toContain("`scripts/escalate.py`");

    const { status, stderr } = aipSpec(["validate", dir]);
    console.log(`scaffold: aip-spec validate ${dir} exited ${status}`);
    expect(stderr).not.toContain("missing_resource");
    expect(specErrors(dir)).toEqual([]);
    expect(status).toBe(0);

    // the template renders with the step's inputs, and the stub prints exactly the declared outputs
    expect(files.get("assets/reply.md")).toContain("{message}");
    expect(files.get("assets/reply.md")).toContain("{assets[policy]}");
    expect(runStub(path.join(dir, "scripts/escalate.py"), { state: { message: "hi", tone: "angry" }, assets: { config: "{}" }, expects: {} }))
      .toEqual({ ticket_id: 0, queue: "" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("the stub prints a dummy of every declared type", () => {
  const root = mkdtempSync(path.join(tmpdir(), "studio-scaffold-"));
  try {
    const draft = billing();
    const escalate = draft.steps.find((s) => s.name === "escalate")!;
    escalate.outputs = [["s", "string"], ["i", "integer"], ["f", "float"], ["b", "boolean"], ["o", "object"], ["l", "list[*]"]].map(([name, type]) => ({ name, type }));
    escalate.description = 'Has """quotes""" and a \\ backslash.';
    const { dir } = writeOut(root, draft);
    const out = runStub(path.join(dir, "scripts/escalate.py"), { state: {}, assets: {}, expects: {} }) as Record<string, unknown>;
    expect(out).toEqual({ s: "", i: 0, f: 0, b: false, o: {}, l: [] });
    // 0.0 stays a float on the wire
    const raw = spawnSync("uv", ["run", "--quiet", "--project", AIP_REPO, "python", path.join(dir, "scripts/escalate.py")], { input: '{"state":{},"assets":{},"expects":{}}', encoding: "utf8" }).stdout;
    expect(raw).toContain('"f": 0.0');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("a draft with errors is marked as a draft, and aip-spec also rejects it with a code the linter reports", () => {
  const root = mkdtempSync(path.join(tmpdir(), "studio-scaffold-"));
  try {
    const draft = billing();
    draft.steps.find((s) => s.name === "end")!.inputs.push({ name: "ghost", type: "string" });
    draft.steps.find((s) => s.name === "reply")!.outputs = [];
    const scaffold = buildScaffold(draft);
    const ts = new Set(scaffold.issues.filter((i) => i.tier === "error").map((i) => i.code));
    const { dir, files } = writeOut(root, draft);
    expect(files.get(README_PATH)).toContain(`DRAFT: ${[...scaffold.issues.filter((i) => i.tier === "error")].length} errors remain`);

    const spec = new Set(specErrors(dir).map((i) => i.kind));
    console.log(`scaffold with errors: linter [${[...ts].sort().join(", ")}], aip-spec [${[...spec].sort().join(", ")}]`);
    expect(aipSpec(["validate", dir]).status).not.toBe(0);
    expect([...spec].filter((c) => ts.has(c)).length).toBeGreaterThan(0);
    expect(spec.has("missing_resource")).toBe(false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
