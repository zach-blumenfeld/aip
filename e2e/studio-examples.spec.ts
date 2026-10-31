import { expect, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { checkResult, type Runner } from "../src/studio/agentCheck";
import { agentGate } from "../src/studio/agentGate";
import { autofix } from "../src/studio/fixes";
import { importSkill } from "../src/studio/import";
import { lint } from "../src/studio/lint";
import { buildScaffold } from "../src/studio/scaffold";
import { utf8, type ZipFile } from "../src/zip";
import { AIP_REPO } from "./aip";
import { aipSpec } from "./aip-spec";

// The designs docs/studio.md walks through (examples/studio/) stay true to what the doc says: expense-review is
// ready for an agent and can be completed so every check passes; meeting-notes has the gaps the doc lists.

const EXAMPLES = path.resolve(import.meta.dirname, "..", "examples", "studio");
const design = (name: string) => importSkill([{ path: "SKILL.md", bytes: new Uint8Array(readFileSync(path.join(EXAMPLES, name, "SKILL.md"))), mode: 0o644 }]);

function writeOut(files: ZipFile[]): { root: string; dir: string } {
  const root = mkdtempSync(path.join(tmpdir(), "studio-example-"));
  const dir = path.join(root, "expense-review");
  for (const f of files) {
    mkdirSync(path.dirname(path.join(dir, f.path)), { recursive: true });
    writeFileSync(path.join(dir, f.path), f.bytes, { mode: f.mode });
  }
  return { root, dir };
}

/** The console's two endpoints, done here directly: aip-spec on a temp folder, and a script under the repo's Python. */
const runner: Runner = {
  async validate(_name, files) {
    const { root, dir } = writeOut(files);
    try {
      const { status, stderr } = aipSpec(["validate", dir]);
      const issues = stderr.split("\n").filter((l) => l.startsWith("{")).map((l) => JSON.parse(l));
      return { valid: status === 0, issues };
    } finally { rmSync(root, { recursive: true, force: true }); }
  },
  async probe(_name, files, script, stdin) {
    const { root, dir } = writeOut(files);
    try {
      const run = spawnSync("uv", ["run", "--quiet", "--project", AIP_REPO, "python", script], { cwd: dir, input: JSON.stringify(stdin), encoding: "utf8" });
      return { code: run.status, stdout: run.stdout, stderr: run.stderr };
    } finally { rmSync(root, { recursive: true, force: true }); }
  },
};

/** What an agent might hand back for expense-review: the scaffold with the placeholders and empty prose filled. */
function filled(scaffold: ZipFile[]): ZipFile[] {
  const text = (p: string) => new TextDecoder().decode(scaffold.find((f) => f.path === p)!.bytes);
  const skillMd = text("SKILL.md")
    .replace('  - name: check-policy\n    kind: decision\n    description: ""', "  - name: check-policy\n    kind: decision\n    description: Decide whether the expense is within the travel policy.")
    .replace('instructions: ""', "instructions: Is the amount within the policy limit for its category (travel 500, meals 75, lodging 250, other 100)?")
    .replace('  - name: approve\n    kind: execution\n    description: ""', "  - name: approve\n    kind: execution\n    description: Issue an approval id for the expense.")
    .replace('  - name: explain\n    kind: client_task\n    description: ""', "  - name: explain\n    kind: client_task\n    description: Tell the submitter which rule the expense breaks.");
  const out: Record<string, string> = {
    "SKILL.md": skillMd,
    "scripts/extract.py": [
      "import json, re, sys", "payload = json.load(sys.stdin)", 'text = payload["state"]["receipt_text"]',
      'm = re.search(r"(\\d+(?:\\.\\d+)?)", text)', 'words = text.split()',
      'category = next((c for c in ("travel", "meals", "lodging") if c in text.lower()), "other")',
      'json.dump({"amount": float(m.group(1)) if m else 0.0, "vendor": words[0] if words else "", "category": category}, sys.stdout)', "",
    ].join("\n"),
    "scripts/approve.py": [
      "import hashlib, json, sys", "payload = json.load(sys.stdin)", 'state = payload["state"]',
      'key = f"{state[\'vendor\']}:{state[\'amount\']}"', 'json.dump({"approval_id": "EXP-" + hashlib.sha256(key.encode()).hexdigest()[:8]}, sys.stdout)', "",
    ].join("\n"),
    "assets/limits.json": '{"travel": 500, "meals": 75, "lodging": 250, "other": 100}\n',
    "assets/explain.md": "The expense below is over policy. Write two sentences to the submitter naming the limit it breaks.\n\nReceipt:\n{receipt_text}\n\nAmount: {amount} ({category})\n\nReturn JSON with `explanation`.\n",
  };
  const keep = scaffold.filter((f) => !(f.path in out));
  return [...keep, ...Object.entries(out).map(([p, t]) => ({ path: p, bytes: utf8(t), mode: p.endsWith(".py") ? 0o755 : 0o644 }))];
}

test.beforeEach(() => {
  test.skip(aipSpec(["--version"]).status !== 0, "aip-spec is not available (needs uv and the aip repo's environment)");
});

test("expense-review is ready for an agent, and a fill-in of it passes every check", async () => {
  const draft = design("expense-review");
  const issues = lint(draft);
  expect(issues.filter((i) => i.tier === "error")).toEqual([]);
  expect(agentGate(draft, issues)).toEqual([]);

  const scaffold = buildScaffold(draft);
  expect(scaffold.placeholders.map((p) => p.path).sort()).toEqual(["assets/explain.md", "assets/limits.json", "scripts/approve.py", "scripts/extract.py"]);
  const { root, dir } = writeOut(scaffold.files);
  try { expect(aipSpec(["validate", dir]).status).toBe(0); } finally { rmSync(root, { recursive: true, force: true }); }

  const verdict = await checkResult(draft, filled(scaffold.files), runner);
  for (const c of verdict.checks) expect(c.failures, c.name).toEqual([]);
  expect(verdict.ok).toBe(true);
  console.log(`expense-review: ${verdict.checks.map((c) => `${c.name} ${c.ok ? "pass" : "fail"}`).join(", ")}; ${verdict.filled.length} prose fields filled`);
});

test("meeting-notes has the gaps the doc lists", () => {
  const draft = design("meeting-notes");
  const codes = new Set(lint(draft).map((i) => `${i.tier}:${i.code}`));
  for (const c of ["error:missing_requires", "error:unproduced_input", "unfinished:empty_purpose", "warning:execution_without_outputs"]) expect(codes, c).toContain(c);
  const reasons = agentGate(draft, lint(draft)).map((r) => r.message);
  expect(reasons.some((r) => r.includes("`purpose`"))).toBe(true);
  expect(reasons.some((r) => r.includes("`clean` declares no outputs"))).toBe(true);

  // the doc's three steps clear the errors: the requires fix, an output on clean, a purpose
  const fix = autofix(lint(draft).find((i) => i.code === "missing_requires")!, draft)!;
  const fixed = fix.apply(draft);
  fixed.steps.find((x) => x.name === "clean")!.outputs = [{ name: "clean_transcript", type: "string" }];
  fixed.purpose = "Turn a transcript into a summary and action items.";
  expect(lint(fixed).filter((i) => i.tier === "error")).toEqual([]);
});
