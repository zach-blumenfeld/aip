import { expect, test } from "@playwright/test";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { Draft, Step } from "../src/studio/draft";
import { lint, STUDIO_ONLY_ERRORS } from "../src/studio/lint";
import { RUNTIME_BLOCK } from "../src/studio/runtime-0.6a1";
import { draftToSkillMd, skillMdToDraft } from "../src/studio/serialize";
import { AIP_REPO, FIRST_REVISION_DIR } from "./aip";
import { aipSpec, specErrors } from "./aip-spec";

// Parity: the same skill text goes through `aip-spec validate` and the TypeScript linter, and the sets of error
// codes must be equal. Fixtures are billing-support with one thing broken per code, plus the spec's own
// dialogue-graph fixture. Two differences are by design and masked: `missing_resource` is not a Studio error (a
// placeholder is `unfinished`), and when the models reject the body (`schema_violation`) aip-spec stops before
// the graph rules, which the linter still runs. Studio-only errors (STUDIO_ONLY_ERRORS) always come with an aip-spec
// error on the same draft and are left out.

const SCHEMA_STAGE = new Set(["schema_violation", "invalid_name", "invalid_description", "missing_required_frontmatter", "invalid_compatibility"]);
const SKILL_DIR_ISSUES = new Set(["missing_resource"]);

const base = () => skillMdToDraft(readFileSync(path.join(FIRST_REVISION_DIR, "SKILL.md"), "utf8"));
const step = (d: Draft, name: string): Step => d.steps.find((s) => s.name === name)!;
const inputs = (...names: [string, string][]) => names.map(([name, type]) => ({ name, type }));

const FIXTURES: Record<string, (d: Draft) => void> = {
  "valid": () => {},
  "duplicate_step_name": (d) => { step(d, "reply").name = "escalate"; },
  "invalid_start_step": (d) => { d.steps.unshift(d.steps.pop()!); },
  "missing_end_step": (d) => { d.steps.pop(); },
  "multiple_end_steps": (d) => { d.steps.push({ ...step(d, "end"), id: "s-end2", name: "end-2" }); },
  "unknown_step_reference": (d) => { step(d, "reply").next = "unresolved:nowhere"; },
  "unreachable_step": (d) => { d.steps.splice(2, 0, { id: "s-orphan", kind: "client_task", name: "orphan", description: "x", inputs: inputs(["message", "string"]), template: "assets/reply.md", outputs: inputs(["extra", "string"]), next: step(d, "end").id }); },
  "no_path_to_end": (d) => { step(d, "reply").next = step(d, "reply").id; },
  "unknown_branch_value": (d) => { step(d, "by-tone").branches![0].value = "furious"; },
  "unproduced_input": (d) => { step(d, "end").inputs.push({ name: "ghost", type: "string" }); },
  "duplicate_producer": (d) => { step(d, "reply").outputs![0].name = "ticket_id"; },
  "duplicate_producer_start_input": (d) => { step(d, "reply").outputs![0].name = "message"; },
  "type_mismatch": (d) => { step(d, "end").inputs[0].type = "integer"; },
  "missing_outputs": (d) => { step(d, "reply").outputs = []; },
  "duplicate_output_name": (d) => { step(d, "reply").outputs!.push({ name: "reply", type: "string" }); },
  "duplicate_input_name": (d) => { step(d, "escalate").inputs.push({ name: "tone", type: "string" }); },
  "unknown_threshold_question": (d) => { step(d, "triage").thresholds!.nope = 0.5; },
  "missing_requires": (d) => { delete d.requires; },
  "undeclared_launcher": (d) => { step(d, "escalate").command = ["bash", "scripts/escalate.py"]; },
  "invalid_name": (d) => { d.name = "Bad_Name"; },
  "missing_name": (d) => { d.name = ""; },
  "invalid_description": (d) => { d.description = ""; },
  "invalid_compatibility": (d) => { d.compatibility = ""; },
  "bad_step_name": (d) => { step(d, "reply").name = "Bad Name"; },
  "choice_with_one_label": (d) => { const q = step(d, "triage").questions![1]; if (q.type === "choice") q.criteria.pop(); },
  "score_with_one_level": (d) => { step(d, "triage").questions![0] = { name: "billing", type: "score", instructions: "x", criteria: ["low"] }; },
  "router_with_one_branch": (d) => { step(d, "by-tone").branches!.pop(); },
  "script_outside_scripts": (d) => { step(d, "escalate").script = "bin/escalate.py"; },
  "asset_outside_assets": (d) => { step(d, "reply").assets = ["policy.md"]; },
  "reference_outside_references": (d) => { step(d, "reply").references![0].path = "help.md"; },
  "bad_input_type": (d) => { step(d, "end").inputs[0].type = "str"; },
  "no_trigger_when": (d) => { d.triggerWhen = []; },
  "one_step": (d) => { d.steps = [step(d, "end")]; },
  "unset_next": (d) => { delete step(d, "reply").next; },
  "bad_package": (d) => { d.requires!.packages = ["not a package"]; },
  "router_loop_valid": (d) => {
    const reply = step(d, "reply");
    reply.outputs!.push({ name: "ok", type: "boolean" });
    const again: Step = { id: "s-again", kind: "router", name: "again", description: "x", inputs: [], branchOn: "ok", branches: [{ value: "true", target: step(d, "end").id }, { value: "false", target: reply.id }] };
    reply.next = again.id;
    d.steps.splice(d.steps.indexOf(reply) + 1, 0, again);
  },
  "router_loop_unproduced": (d) => {
    const reply = step(d, "reply");
    reply.outputs!.push({ name: "ok", type: "boolean" });
    reply.inputs.push({ name: "ok", type: "boolean" });
    const again: Step = { id: "s-again", kind: "router", name: "again", description: "x", inputs: [], branchOn: "ok", branches: [{ value: "true", target: step(d, "end").id }, { value: "false", target: reply.id }] };
    reply.next = again.id;
    d.steps.splice(d.steps.indexOf(reply) + 1, 0, again);
  },
};

/** A skill folder named for the skill: billing-support's files, and the given SKILL.md. */
function folder(root: string, name: string, skillMd: string): string {
  const dir = path.join(root, name || "unnamed");
  cpSync(path.dirname(path.join(FIRST_REVISION_DIR, "SKILL.md")), dir, { recursive: true });
  writeFileSync(path.join(dir, "SKILL.md"), skillMd);
  return dir;
}

function compare(label: string, name: string, text: string, root: string): { label: string; spec: string[]; ts: string[] } {
  const dir = folder(root, name, text);
  const spec = new Set(specErrors(dir).map((i) => i.kind));
  for (const k of SKILL_DIR_ISSUES) spec.delete(k);
  let ts = new Set(lint(skillMdToDraft(text)).filter((i) => i.tier === "error" && !STUDIO_ONLY_ERRORS.has(i.code)).map((i) => i.code));
  // The folder is named for the skill, so `name_mismatch` cannot differ; a skill with no name sits in `unnamed/`.
  if (spec.has("schema_violation")) {
    ts = new Set([...ts].filter((c) => SCHEMA_STAGE.has(c)));
  }
  return { label, spec: [...spec].sort(), ts: [...ts].sort() };
}

test("the TypeScript linter and aip-spec agree on the error codes", () => {
  test.skip(aipSpec(["--version"]).status !== 0, "aip-spec is not available (needs uv and the aip repo's environment)");
  const root = mkdtempSync(path.join(tmpdir(), "studio-parity-"));
  try {
    const results = Object.entries(FIXTURES).map(([label, edit]) => {
      const draft = base();
      edit(draft);
      return compare(label, draft.name, draftToSkillMd(draft), path.join(root, label));
    });

    // The spec's own fixture: the dialogue graph, a 0.5a1 body that fails the state rules.
    const dialogue = path.join(AIP_REPO, "packages", "aip-spec", "tests", "fixtures", "dialogue-graph.yaml");
    if (existsSync(dialogue)) {
      const text = `---\nname: dialogue-graph\ndescription: Parse a dialogue script into a graph.\nmetadata:\n  aip-version: "0.6a1"\n---\n\n${RUNTIME_BLOCK.trim()}\n\n\`\`\`yaml\n${readFileSync(dialogue, "utf8")}\n\`\`\`\n`;
      mkdirSync(path.join(root, "dialogue"), { recursive: true });
      results.push(compare("dialogue-graph", "dialogue-graph", text, path.join(root, "dialogue")));
    }

    const disagreements = results.filter((r) => JSON.stringify(r.spec) !== JSON.stringify(r.ts));
    console.log(`lint parity: ${results.length} fixtures compared, ${disagreements.length} disagreements`);
    for (const r of results) console.log(`  ${r.label.padEnd(30)} ${r.spec.join(",") || "(valid)"}`);
    expect(disagreements).toEqual([]);
    expect(results.find((r) => r.label === "valid")!.spec).toEqual([]);
    expect(new Set(results.flatMap((r) => r.spec)).size).toBeGreaterThanOrEqual(20);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
