// The Studio's field edits (src/studio/edit.ts), on the examples' own source and the graphs `aip compile
// --json` printed for them (test/fixtures). Each edit is checked as the text it makes; the e2e spec
// (e2e/studio.spec.ts) checks that the compiler and the formatter agree with it.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { applyEdits, connect, setAtCap, setBound, setLabels, setText, setUntil, targetsFor } from "../src/studio/edit.ts";
import type { Graph } from "../src/graph/bundle.ts";

const graph = (name: string) => JSON.parse(readFileSync(path.join(import.meta.dirname, "fixtures", `${name}.graph.json`), "utf8")) as Graph;
const source = (name: string) => readFileSync(path.join(import.meta.dirname, "..", "..", "examples", "language", name, "procedure.aip"), "utf8");
const edge = (g: Graph, type: string, start: string, value?: string) =>
  g.edges.find((e) => e.type === type && e.start === start && (value === undefined || e.properties.value === value))!;

const BILLING = source("billing-support"), TRIAGE = source("ticket-triage"), AGENT = source("billing-support-agent");
const billing = graph("billing-support"), triage = graph("ticket-triage"), agent = graph("billing-support-agent");

test("edits apply against the text as it was, last first", () => {
  assert.equal(applyEdits("ab\ncd\n", [{ line: 1, column: 2, endLine: 2, endColumn: 2, text: "X" }, { line: 1, column: 1, endLine: 1, endColumn: 1, text: ">" }]), ">aXd\n");
});

test("where a step goes next: its target rewritten, among the steps of its block", () => {
  assert.ok(applyEdits(BILLING, connect(BILLING, edge(billing, "BRANCH", "step:by_tone", "calm"), "escalate")).includes("  calm  -> escalate\n"));
  assert.ok(applyEdits(BILLING, connect(BILLING, edge(billing, "NEXT", "step:triage"), "end")).includes("  Produce triage_decision\n  Next_Step end\n"));
  assert.ok(applyEdits(BILLING, connect(BILLING, edge(billing, "BELOW", "step:by_tone"), "reply")).includes("Confidence_Below 0.9 -> reply\n"));
  // A step's `Continue` becomes a Next_Step, and back.
  const fix = edge(triage, "CONTINUES", "step:fix");
  assert.ok(applyEdits(TRIAGE, connect(TRIAGE, fix, "check")).includes("      Produce reply: string\n      Next_Step check\n    }"));
  assert.ok(applyEdits(TRIAGE, connect(TRIAGE, edge(triage, "NEXT", "step:check"), "Continue")).includes("      Produce passed: true_or_false\n      Continue\n"));
  assert.deepEqual(targetsFor(billing, "step:triage"), ["by_tone", "escalate", "reply", "end"]);
  assert.ok(targetsFor(triage, "step:fix").includes("Continue") && !targetsFor(triage, "step:fix").includes("end"));
  assert.ok(targetsFor(triage, "loop:revise").includes("draft"), "a loop's exit leads within the block it is in");
});

test("bars and caps: a route's check, a loop's cap", () => {
  assert.ok(applyEdits(BILLING, setBound(BILLING, billing, "step:by_tone", 0.75)).includes("Confidence_Below 0.75 -> escalate"));
  assert.ok(applyEdits(TRIAGE, setBound(TRIAGE, triage, "loop:revise", 6)).includes("Loop revise Until passed, At_Most 6, Else_Fail {"));
  assert.ok(applyEdits(TRIAGE, setBound(TRIAGE, triage, "loop:each_ticket", 20)).includes("At_Most 20"));
  assert.throws(() => setBound(BILLING, billing, "step:reply", 1), /no bound/);
});

test("a loop's Until and what it does at its cap", () => {
  const until = applyEdits(TRIAGE, setUntil(TRIAGE, triage, "loop:revise", "passed With  Confidence_Above 0.8"));
  assert.ok(until.includes("Loop revise Until passed With Confidence_Above 0.8, At_Most 4, Else_Fail {"), until);
  assert.ok(applyEdits(TRIAGE, setAtCap(TRIAGE, triage, "loop:revise", "Else_Exit")).includes("Loop revise Until passed, At_Most 4, Else_Exit {"));
  assert.throws(() => setUntil(TRIAGE, triage, "loop:each_ticket", "passed"), /no Until/);
  assert.throws(() => setUntil(TRIAGE, triage, "loop:revise", "a, b"), /no comma/);
  assert.throws(() => setAtCap(TRIAGE, triage, "step:fix", "Else_Exit"), /not a loop/);
});

test("descriptions, the procedure's, and a question's instruction, through a named string when it is one", () => {
  assert.ok(applyEdits(BILLING, setText(BILLING, billing, "step:reply", 'Draft a "kind" reply.')).includes('Task_Agent With reply "Draft a \\"kind\\" reply." {'));
  assert.ok(applyEdits(BILLING, setText(BILLING, billing, "question:triage.billing", "About money?")).includes('billing: true_or_false "About money?"'));
  const named = applyEdits(BILLING, setText(BILLING, billing, "question:triage.tone", "Upset?"));
  assert.ok(named.includes('tone_question  = "Upset?"') && named.includes("choice [angry, calm] tone_question"));
  assert.ok(applyEdits(BILLING, setText(BILLING, billing, "procedure", "Triage billing.")).includes('Procedure billing_support\n  "Triage billing."\n'));
});

test("labels: a question's, renamed on its criteria and on the route's branches", () => {
  const out = applyEdits(BILLING, setLabels(BILLING, billing, "question:triage.tone", ["upset", "calm"]));
  assert.ok(out.includes("tone:    choice [upset, calm] tone_question\n      upset: \"Frustrated"), out);
  assert.ok(out.includes("  upset -> escalate\n  calm  -> reply\n"), out);
  assert.ok(out.includes("Read message, triage_decision.tone\n"), "a read of the answer is not a label");
  // A label added is the compiler's to report on the route that does not name it.
  const added = applyEdits(BILLING, setLabels(BILLING, billing, "question:triage.tone", ["angry", "calm", "unsure"]));
  assert.ok(added.includes("choice [angry, calm, unsure] tone_question") && added.includes("  angry -> escalate\n"));
  assert.throws(() => setLabels(BILLING, billing, "question:triage.tone", ["angry"]), /at least two/);
  assert.throws(() => setLabels(BILLING, billing, "question:triage.tone", ["Angry", "calm"]), /not a label/);
  assert.throws(() => setLabels(BILLING, billing, "question:triage.billing", ["yes", "no"]), /no labels in brackets/);
});

test("labels: a key an agent produces with an answer type, and the route on it", () => {
  const out = applyEdits(AGENT, setLabels(AGENT, agent, "data:tone", ["furious", "calm"]));
  assert.ok(out.includes('tone:    choice [furious, calm] "How upset the customer is."'), out);
  assert.ok(out.includes("  furious -> escalate\n  calm  -> reply\n"), out);
});
