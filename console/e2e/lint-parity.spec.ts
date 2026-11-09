import { expect, test } from "@playwright/test";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { Draft, Step } from "../src/studio/draft";
import { classifySources, lint, STUDIO_ONLY_ERRORS, STUDIO_ONLY_WARNINGS, type Tier } from "../src/studio/lint";
import { RUNTIME_BLOCK } from "../src/studio/runtime-0.8";
import { draftToSkillMd, skillMdToDraft } from "../src/studio/serialize";
import { AIP_REPO, EXAMPLE_DIR } from "./aip";
import { aipSpec, specIssues } from "./aip-spec";

// Parity: the same skill text goes through `aip-spec validate` and the TypeScript linter, and the sets of codes
// must be equal at every severity: the errors, the warnings (a route an LLM steers with nothing recorded) and the
// infos (a key with several producers). Fixtures are billing-support with one thing broken per code, plus the
// spec's own dialogue-graph fixture. Two differences are by design and masked: `missing_resource` is not a Studio
// error (a placeholder is `unfinished`), and when the models reject the body (`schema_violation`) aip-spec stops
// before the graph rules, which the linter still runs. The Studio's own codes (STUDIO_ONLY_ERRORS, which always
// come with an aip-spec error on the same draft, and STUDIO_ONLY_WARNINGS) are left out.

const SCHEMA_STAGE = new Set(["schema_violation", "invalid_name", "invalid_description", "missing_required_frontmatter", "invalid_compatibility"]);
const SKILL_DIR_ISSUES = new Set(["missing_resource"]);
const SEVERITIES = ["error", "warning", "info"] as const;

const base = () => skillMdToDraft(readFileSync(path.join(EXAMPLE_DIR, "SKILL.md"), "utf8"));
const step = (d: Draft, name: string): Step => d.steps.find((s) => s.name === name)!;
const inputs = (...names: [string, string][]) => names.map(([name, type]) => ({ name, type }));
/** The example with its route measured: `fallback` off, so no warning at all; every source-class case starts here. */
const measured = (d: Draft) => { step(d, "triage").fallback = false; };

const FIXTURES: Record<string, (d: Draft) => void> = {
  // the shipped example: `fallback: true` for the quickstart, and the router checks `tone_confidence` all the same
  "valid_with_the_examples_warning": () => {},
  "valid": measured,
  "duplicate_step_name": (d) => { step(d, "reply").name = "escalate"; },
  "missing_start_step": (d) => { d.steps.shift(); },
  "multiple_start_steps": (d) => { d.steps.push({ ...step(d, "start"), id: "s-start2", name: "again" }); },
  "start_anywhere_valid": (d) => { measured(d); d.steps.push(d.steps.shift()!); },
  "edge_into_start": (d) => { step(d, "escalate").next = step(d, "start").id; },
  "branch_into_start": (d) => { step(d, "by-tone").branches![0].target = step(d, "start").id; },
  "missing_end_step": (d) => { d.steps.pop(); },
  "multiple_end_steps": (d) => { d.steps.push({ ...step(d, "end"), id: "s-end2", name: "end-2" }); },
  "unknown_step_reference": (d) => { step(d, "reply").next = "unresolved:nowhere"; },
  "unknown_check_target": (d) => { step(d, "by-tone").check!.to = "unresolved:nowhere"; },
  "check_target_only_reached_by_the_check": (d) => {
    measured(d);
    d.steps.splice(4, 0, { id: "s-review", kind: "client_task", name: "review", description: "x", inputs: [], template: "assets/reply.md", outputs: inputs(["notes", "string"]), next: step(d, "end").id });
    step(d, "by-tone").check!.to = "s-review";
  },
  "unreachable_step": (d) => { d.steps.splice(2, 0, { id: "s-orphan", kind: "client_task", name: "orphan", description: "x", inputs: inputs(["message", "string"]), template: "assets/reply.md", outputs: inputs(["extra", "string"]), next: step(d, "end").id }); },
  "no_path_to_end": (d) => { step(d, "reply").next = step(d, "reply").id; },
  "unknown_branch_value": (d) => { step(d, "by-tone").branches![0].value = "furious"; },
  "unproduced_input": (d) => { step(d, "end").inputs.push({ name: "ghost", type: "string" }); },
  "start_input_declared_by_the_fix": (d) => { measured(d); step(d, "escalate").inputs.push({ name: "account_id", type: "string" }); step(d, "start").inputs.push({ name: "account_id", type: "string" }); },
  "unproduced_check_key": (d) => { step(d, "triage").confidence = []; },
  "check_key_on_one_path_is_enough": (d) => {
    measured(d);
    step(d, "escalate").outputs!.push({ name: "tone", type: "string" });
    const again: Step = { id: "s-again", kind: "router", name: "by-tone-again", description: "x", inputs: [], branchOn: "tone",
      check: { key: "tone_confidence", below: 0.6, to: step(d, "reply").id }, branches: [{ value: "angry", target: step(d, "end").id }, { value: "calm", target: step(d, "reply").id }] };
    step(d, "escalate").next = again.id;
    step(d, "end").inputs = [];
    d.steps.splice(4, 0, again);
  },
  "duplicate_producer": (d) => { step(d, "reply").outputs![0].name = "ticket_id"; },
  "duplicate_producer_start_input": (d) => { step(d, "reply").outputs![0].name = "message"; },
  "overwritten_start_input_with_another_type": (d) => { step(d, "escalate").outputs!.push({ name: "message", type: "object" }); },
  "type_mismatch": (d) => { step(d, "end").inputs[0].type = "integer"; },
  "type_mismatch_with_a_question": (d) => { step(d, "reply").inputs[1].type = "integer"; },
  "type_mismatch_first_declaration_wins": (d) => { step(d, "escalate").outputs![0].type = "string"; step(d, "reply").outputs!.push({ name: "ticket_id", type: "integer" }); },
  "type_mismatch_check_key_is_the_answer": (d) => { step(d, "by-tone").check!.key = "tone"; },
  "type_mismatch_confidence_key_read_as_integer": (d) => { step(d, "reply").inputs.push({ name: "tone_confidence", type: "integer" }); },
  "unbranchable_type": (d) => {
    step(d, "escalate").outputs!.push({ name: "payload", type: "object" });
    const router: Step = { id: "s-payload", kind: "router", name: "by-payload", description: "x", inputs: [], branchOn: "payload", branches: [{ value: "a", target: step(d, "end").id }, { value: "b", target: step(d, "end").id }] };
    step(d, "escalate").next = router.id;
    d.steps.splice(4, 0, router);
  },
  "missing_outputs": (d) => { step(d, "reply").outputs = []; },
  "duplicate_output_name": (d) => { step(d, "reply").outputs!.push({ name: "reply", type: "string" }); },
  "duplicate_input_name": (d) => { step(d, "escalate").inputs.push({ name: "tone", type: "string" }); },
  "duplicate_start_input_name": (d) => { step(d, "start").inputs.push({ name: "message", type: "string" }); },
  "unknown_confidence_question": (d) => { step(d, "triage").confidence!.push("nope"); },
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
  "check_bound_out_of_range": (d) => { step(d, "by-tone").check!.below = 1.5; },
  "check_without_a_target": (d) => { delete step(d, "by-tone").check!.to; },
  "bad_confidence_name": (d) => { step(d, "triage").confidence = ["1tone"]; },
  "script_outside_scripts": (d) => { step(d, "escalate").script = "bin/escalate.py"; },
  "asset_outside_assets": (d) => { step(d, "reply").assets = ["policy.md"]; },
  "reference_outside_references": (d) => { step(d, "reply").references![0].path = "help.md"; },
  "bad_input_type": (d) => { step(d, "end").inputs[0].type = "str"; },
  "no_trigger_when": (d) => { d.triggerWhen = []; },
  "two_steps": (d) => { d.steps = [step(d, "start"), step(d, "end")]; },
  "unset_next": (d) => { delete step(d, "reply").next; },
  "unset_start_next": (d) => { delete step(d, "start").next; },
  "bad_package": (d) => { d.requires!.packages = ["not a package"]; },
  "router_loop_valid": (d) => {
    measured(d);
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
  // the sources of a route (aip-spec's RouteSources tests)
  "unmeasured_route_no_confidence_list": (d) => { measured(d); delete step(d, "triage").confidence; delete step(d, "by-tone").check; },
  "unmeasured_route_confidence_not_checked": (d) => { measured(d); delete step(d, "by-tone").check; },
  "unmeasured_route_fallback": (d) => { delete step(d, "by-tone").check; },
  "deterministic_start_input": (d) => {
    measured(d);
    step(d, "start").inputs.push({ name: "tone", type: "string" });
    d.steps.splice(d.steps.indexOf(step(d, "triage")), 1);
    step(d, "start").next = step(d, "by-tone").id;
    delete step(d, "by-tone").check;
  },
  "deterministic_script_output": (d) => {
    measured(d);
    step(d, "start").inputs.push({ name: "tone", type: "string" });
    d.steps.splice(d.steps.indexOf(step(d, "triage")), 1);
    delete step(d, "by-tone").check;
    const sort: Step = { id: "s-sort", kind: "execution", name: "sort", description: "x", inputs: inputs(["message", "string"]), script: "scripts/escalate.py", outputs: inputs(["tone", "string"]), next: step(d, "by-tone").id };
    step(d, "start").next = sort.id;
    d.steps.splice(1, 0, sort);
  },
  "unmeasured_client_task_output": (d) => {
    measured(d);
    step(d, "reply").outputs!.push({ name: "tone", type: "string" });
    step(d, "reply").next = step(d, "by-tone").id;
    step(d, "end").inputs.push({ name: "ticket_id", type: "integer" });
  },
  "declared_confidence_of_a_script_beside_an_unmeasured_decision": (d) => {
    measured(d);
    delete step(d, "triage").confidence;
    step(d, "escalate").outputs!.push({ name: "tone", type: "string" }, { name: "sureness", type: "float" });
    step(d, "escalate").next = step(d, "by-tone").id;
    step(d, "by-tone").branches![0].target = step(d, "end").id;
    step(d, "end").inputs = [];
    step(d, "by-tone").check!.key = "sureness";
  },
  "declared_confidence_of_a_script": (d) => {
    measured(d);
    step(d, "escalate").outputs!.push({ name: "tone", type: "string" }, { name: "tone_confidence", type: "float" });
    step(d, "escalate").next = step(d, "by-tone").id;
    step(d, "by-tone").branches![0].target = step(d, "end").id;
    step(d, "end").inputs = [];
  },
  "declared_confidence_of_a_client_task": (d) => {
    measured(d);
    step(d, "reply").outputs!.push({ name: "tone", type: "string" }, { name: "tone_confidence", type: "float" });
    step(d, "reply").next = step(d, "by-tone").id;
    step(d, "end").inputs.push({ name: "ticket_id", type: "integer" });
  },
};

/** A skill folder named for the skill: billing-support's files, and the given SKILL.md. */
function folder(root: string, name: string, skillMd: string): string {
  const dir = path.join(root, name || "unnamed");
  cpSync(path.dirname(path.join(EXAMPLE_DIR, "SKILL.md")), dir, { recursive: true });
  writeFileSync(path.join(dir, "SKILL.md"), skillMd);
  return dir;
}

type Codes = Record<(typeof SEVERITIES)[number], string[]>;

function compare(label: string, name: string, text: string, root: string): { label: string; spec: Codes; ts: Codes } {
  const dir = folder(root, name, text);
  const issues = specIssues(dir).filter((i) => !SKILL_DIR_ISSUES.has(i.kind));
  const own = (tier: Tier, code: string) => (tier === "error" && STUDIO_ONLY_ERRORS.has(code)) || (tier === "warning" && STUDIO_ONLY_WARNINGS.has(code));
  const linted = lint(skillMdToDraft(text)).filter((i) => i.tier !== "unfinished" && !own(i.tier, i.code));
  const codes = (list: { tier: string; code: string }[]): Codes => Object.fromEntries(SEVERITIES.map((sev) => [sev, [...new Set(list.filter((i) => i.tier === sev).map((i) => i.code))].sort()])) as Codes;
  const spec = codes(issues.map((i) => ({ tier: i.severity, code: i.kind })));
  let ts = codes(linted);
  // The folder is named for the skill, so `name_mismatch` cannot differ; a skill with no name sits in `unnamed/`.
  // When the models reject the body, aip-spec stops before the graph rules: only the schema-stage errors compare.
  if (spec.error.includes("schema_violation")) ts = { error: ts.error.filter((c) => SCHEMA_STAGE.has(c)), warning: [], info: [] };
  return { label, spec, ts };
}

test("the TypeScript linter and aip-spec agree on the codes at every severity", () => {
  test.skip(aipSpec(["--version"]).status !== 0, "aip-spec is not available (needs uv and the aip repo's environment)");
  const root = mkdtempSync(path.join(tmpdir(), "studio-parity-"));
  try {
    const results = Object.entries(FIXTURES).map(([label, edit]) => {
      const draft = base();
      edit(draft);
      return compare(label, draft.name, draftToSkillMd(draft), path.join(root, label));
    });

    // The spec's own fixture: the dialogue graph, a 0.5a1 body moved to 0.8 that fails the state rules.
    const dialogue = path.join(AIP_REPO, "packages", "aip-spec", "tests", "fixtures", "dialogue-graph.yaml");
    if (existsSync(dialogue)) {
      const text = `---\nname: dialogue-graph\ndescription: Parse a dialogue script into a graph.\nmetadata:\n  aip-version: "0.8"\n---\n\n${RUNTIME_BLOCK.trim()}\n\n\`\`\`yaml\n${readFileSync(dialogue, "utf8")}\n\`\`\`\n`;
      mkdirSync(path.join(root, "dialogue"), { recursive: true });
      results.push(compare("dialogue-graph", "dialogue-graph", text, path.join(root, "dialogue")));
    }

    const disagreements = results.filter((r) => JSON.stringify(r.spec) !== JSON.stringify(r.ts));
    console.log(`lint parity: ${results.length} fixtures compared, ${disagreements.length} disagreements`);
    const show = (c: Codes) => SEVERITIES.flatMap((sev) => c[sev].map((code) => (sev === "error" ? code : `${code} (${sev})`))).join(", ") || "(valid)";
    for (const r of results) console.log(`  ${r.label.padEnd(58)} ${show(r.spec)}`);
    expect(disagreements).toEqual([]);
    expect(results.find((r) => r.label === "valid")!.spec).toEqual({ error: [], warning: [], info: [] });
    expect(results.find((r) => r.label === "valid_with_the_examples_warning")!.spec).toEqual({ error: [], warning: ["confidence_on_unmeasured_source"], info: [] });
    expect(new Set(results.flatMap((r) => r.spec.error)).size).toBeGreaterThanOrEqual(24);
    expect(new Set(results.flatMap((r) => r.spec.warning))).toEqual(new Set(["confidence_on_unmeasured_source", "unmeasured_route"]));
    expect(new Set(results.flatMap((r) => r.spec.info))).toEqual(new Set(["duplicate_producer", "declared_confidence"]));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("the source classes follow aip-spec's", () => {
  const cls = (edit: (d: Draft) => void) => { const d = base(); edit(d); return classifySources(d).get(step(d, "by-tone").id); };
  expect(cls(() => {})).toBe("unmeasured");                          // fallback on
  expect(cls(measured)).toBe("measured");
  expect(cls(FIXTURES.unmeasured_route_confidence_not_checked)).toBe("unmeasured");
  expect(cls(FIXTURES.deterministic_start_input)).toBe("deterministic");
  expect(cls(FIXTURES.deterministic_script_output)).toBe("deterministic");
  expect(cls(FIXTURES.unmeasured_client_task_output)).toBe("unmeasured");   // the worst producer wins
  expect(cls(FIXTURES.declared_confidence_of_a_script)).toBe("measured");
  expect(cls(FIXTURES.declared_confidence_of_a_script_beside_an_unmeasured_decision)).toBe("unmeasured");
});
