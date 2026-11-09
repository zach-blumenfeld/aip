import { expect, test } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { parse } from "yaml";
import { emptyDraft, type Draft, type Step } from "../src/studio/draft";
import { availableKeys, classifySources, lint, PLACEHOLDER_MARKER } from "../src/studio/lint";
import { RUNTIME_BLOCK } from "../src/studio/runtime-0.8";
import { draftToSkillMd, skillMdToDraft } from "../src/studio/serialize";
import { AIP_REPO, EXAMPLE_DIR } from "./aip";
import { aipSpec } from "./aip-spec";

// The Studio's model and linter, no browser: the Draft round-trips through SKILL.md, billing-support lints
// clean, and each tier and the cycle-aware state rule behave. The parity spec checks the same linter against
// the real `aip-spec validate`.

const billing = () => readFileSync(path.join(EXAMPLE_DIR, "SKILL.md"), "utf8");
const codes = (d: Draft, tier?: string) => [...new Set(lint(d).filter((i) => !tier || i.tier === tier).map((i) => i.code))].sort();
const step = (d: Draft, name: string): Step => d.steps.find((s) => s.name === name)!;

/** The body YAML of a SKILL.md, parsed. */
const body = (md: string) => parse(/```yaml\n(.*)\n```/s.exec(md)![1]);

test("the embedded runtime block is the one aip-spec ships", () => {
  expect(aipSpec(["runtime"]).stdout).toBe(RUNTIME_BLOCK);
  const file = path.join(AIP_REPO, "packages", "aip-spec", "src", "aip_spec", "runtime.md");
  if (existsSync(file)) expect(readFileSync(file, "utf8")).toBe(RUNTIME_BLOCK);
});

test("billing-support round-trips through the Draft", () => {
  const md = billing();
  const draft = skillMdToDraft(md);
  expect(draft.steps.map((s) => s.name)).toEqual(["start", "triage", "by-tone", "escalate", "reply", "end"]);
  const out = draftToSkillMd(draft);
  expect(body(out)).toEqual(body(md));
  expect(skillMdToDraft(out)).toEqual(draft);
  expect(out.indexOf("# AIP runtime")).toBeGreaterThan(0);
});

/** The issues aip-spec's own rules reject a skill for, without the warnings, aip-spec's and the Studio's (S5). */
const strict = (d: Draft) => lint(d).filter((i) => i.tier !== "warning");

test("billing-support lints clean, but for aip-spec's warning on its route and one Studio-only warning", () => {
  const draft = skillMdToDraft(billing());
  expect(strict(draft)).toEqual([]);
  // the example keeps `fallback: true` so the quickstart runs without a key, and its router checks `tone_confidence`
  // all the same; and the step `reply` outputs a key `reply`
  expect(lint(draft).map((i) => [i.tier, i.code, i.stepId])).toEqual([
    ["warning", "confidence_on_unmeasured_source", step(draft, "by-tone").id],
    ["warning", "name_collision", step(draft, "reply").id],
  ]);
});

test("a decision model with its confidence checked measures the route: no warning at all", () => {
  const draft = skillMdToDraft(billing());
  step(draft, "triage").fallback = false;
  step(draft, "reply").name = "draft-reply";
  expect(lint(draft)).toEqual([]);
  expect(classifySources(draft).get(step(draft, "by-tone").id)).toBe("measured");
});

test("a blank draft: errors for what the spec requires, unfinished for what a template may leave", () => {
  const blank = emptyDraft();
  expect(codes(blank, "error")).toEqual(["invalid_description", "missing_required_frontmatter", "schema_violation"]);
  expect(codes(blank, "unfinished")).toEqual(["empty_purpose", "empty_trigger_when"]);
});

test("a step's rename moves with its edges", () => {
  const draft = skillMdToDraft(billing());
  step(draft, "reply").name = "draft-reply";
  expect(lint(draft).map((i) => i.code)).toEqual(["confidence_on_unmeasured_source"]);   // and the name no longer collides with the key
  expect(draftToSkillMd(draft)).toContain("calm: draft-reply");
});

test("unfinished: empty prose, an end with no inputs, a placeholder file, a launcher other than python", () => {
  const draft = skillMdToDraft(billing());
  draft.purpose = "";
  step(draft, "triage").description = "";
  step(draft, "triage").questions![0].instructions = "";
  step(draft, "end").inputs = [];
  step(draft, "escalate").command = ["bash", "run.sh"];
  draft.requires!.tools = ["bash"];
  const issues = lint(draft, { files: { "assets/reply.md": `# ${PLACEHOLDER_MARKER}\n`, "assets/policy.md": "real text" } }).filter((i) => i.tier !== "warning");
  expect(issues.filter((i) => i.tier === "error")).toEqual([]);
  expect(issues.map((i) => i.code).sort()).toEqual(
    ["empty_description", "empty_instructions", "empty_purpose", "end_without_inputs", "non_python_launcher", "placeholder_file"],
  );
  expect(issues.find((i) => i.code === "placeholder_file")).toMatchObject({ stepId: step(draft, "reply").id, tier: "unfinished" });
});

/** billing-support with a retry loop: reply reports `ok`; a router sends false back to reply. */
function looped(): Draft {
  const draft = skillMdToDraft(billing());
  const reply = step(draft, "reply");
  reply.outputs!.push({ name: "ok", type: "boolean" });
  const again: Step = {
    id: "s-again", kind: "router", name: "again", description: "Retry until the reply is accepted.", inputs: [], branchOn: "ok",
    branches: [{ value: "true", target: step(draft, "end").id }, { value: "false", target: reply.id }],
  };
  reply.next = again.id;
  draft.steps.splice(draft.steps.indexOf(reply) + 1, 0, again);
  return draft;
}

test("a router loop is valid when its keys are produced before it", () => {
  const draft = looped();
  expect(strict(draft)).toEqual([]);
  expect(body(draftToSkillMd(draft)).steps.find((s: { name: string }) => s.name === "again").branches).toEqual({ true: "end", false: "reply" });
});

test("must-availability crosses a cycle: a key produced only inside the loop is not available at its head", () => {
  const draft = looped();
  step(draft, "reply").inputs.push({ name: "ok", type: "boolean" });   // reply reads what reply itself produces
  const issues = lint(draft).filter((i) => i.tier === "error");
  expect(issues.map((i) => i.code)).toEqual(["unproduced_input"]);
  expect(issues[0].stepId).toBe(step(draft, "reply").id);
});

test("the graph rules name the step", () => {
  const draft = skillMdToDraft(billing());
  step(draft, "reply").next = "unresolved:nowhere";
  const issues = lint(draft);
  expect(issues.find((i) => i.code === "unknown_step_reference")).toMatchObject({ tier: "error", stepId: step(draft, "reply").id, field: "next" });
  expect(codes(draft, "error")).toContain("no_path_to_end");
});

test("availableKeys offers only the keys on every path to a step", () => {
  const d = skillMdToDraft(billing());
  const at = (name: string) => availableKeys(d).get(step(d, name).id)!.map((k) => k.name);
  // escalate and reply each produce a key, but only one of them runs, so neither is certain at the end
  expect(at("escalate")).toEqual(expect.arrayContaining(["tone"]));
  expect(at("end")).not.toContain("ticket_id");
  expect(at("end")).not.toContain("reply");
  expect(at("end")).toEqual(expect.arrayContaining(["tone"]));
  // and the type is the one the key is declared with
  expect(availableKeys(d).get(step(d, "by-tone").id)!.find((k) => k.name === "tone")?.type).toBe("string");
});
