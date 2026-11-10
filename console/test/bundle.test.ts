// The bundle's graph read as steps and loops (src/graph/bundle.ts), on graphs as `aip compile --json` printed them for three of the
// example programs (test/fixtures/*.graph.json; scratch them again from the examples when the graph's
// schema moves: aip docs/language/bundle.md).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { modelOf, sliceOf, type Graph } from "../src/graph/bundle.ts";

const graph = (name: string) => JSON.parse(readFileSync(path.join(import.meta.dirname, "fixtures", `${name}.graph.json`), "utf8")) as Graph;

test("one card per step: kind, description as title, what it reads and produces", () => {
  const model = modelOf(graph("billing-support"));
  assert.equal(model.name, "billing_support");
  assert.deepEqual(model.top, ["step:start", "step:triage", "step:by_tone", "step:escalate", "step:reply", "step:end"]);
  assert.deepEqual(Object.keys(model.frames), []);

  const triage = model.cards["step:triage"];
  assert.equal(triage.kind, "Decide");
  assert.equal(triage.title, "Classify whether the message is about billing and how upset the customer is.");
  assert.deepEqual(triage.sections, [
    { label: "reads", rows: ["message"] },
    { label: "asks", rows: ["billing: true_or_false", "tone: choice [angry, calm]"] },
    { label: "produces", rows: ["triage_decision: decision"] },
  ]);
  assert.deepEqual(model.cards["step:start"].sections, [{ label: "inputs", rows: ["message: string"] }]);
  assert.deepEqual(model.cards["step:escalate"].sections, [
    { label: "reads", rows: ["message", "triage_decision.tone"] },
    { label: "runs", rows: ["scripts/escalate.py"] },
    { label: "uses", rows: ["assets/config.json"] },
    { label: "produces", rows: ["ticket_id: integer", "queue: string"] },
  ]);
  assert.deepEqual(model.cards["step:reply"].sections.find((s) => s.label === "prompt"), { label: "prompt", rows: ["assets/reply.md"] });
});

test("a port per way out, quoting where it leads; a route has one per label and one for its check", () => {
  const model = modelOf(graph("billing-support"));
  const next = model.cards["step:triage"].ports;
  assert.equal(next.length, 1);
  assert.deepEqual({ kind: next[0].kind, label: next[0].label, target: next[0].target }, { kind: "next", label: "next", target: "step:by_tone" });
  assert.match(next[0].quote, /^Angry customers, and those the model is unsure of/);
  assert.equal(typeof next[0].line, "number");

  const route = model.cards["step:by_tone"];
  assert.deepEqual(route.sections, [{ label: "reads", rows: ["triage_decision.tone"] }, { label: "routes on", rows: ["measured answer"] }]);
  assert.deepEqual(route.ports.map((p) => [p.kind, p.label, p.target]), [
    ["below", "confidence below 0.9", "step:escalate"],
    ["branch", "angry", "step:escalate"],
    ["branch", "calm", "step:reply"],
  ]);
  assert.equal(route.ports[2].quote, model.cards["step:reply"].title);
  assert.deepEqual(model.cards["step:end"].ports, []);
});

test("a loop is a frame around its body, with its header and its own way out", () => {
  const model = modelOf(graph("fixed-policy"));
  assert.deepEqual(model.top, ["step:start", "step:draft", "loop:revise", "step:end"]);
  const revise = model.frames["loop:revise"];
  assert.equal(revise.kind, "Loop");
  assert.equal(revise.header, "Until check_summary.all_hold, At_Most 3, Else_Fail");
  assert.deepEqual(revise.children, ["step:check", "step:summarize_check", "step:fix"]);
  assert.deepEqual(revise.ports.map((p) => [p.kind, p.target]), [["next", "step:end"]]);
  assert.equal(model.cards["step:fix"].parent, "loop:revise");
  assert.deepEqual(model.cards["step:fix"].ports.map((p) => [p.kind, p.target, p.quote]), [["continue", "loop:revise", "the next pass of revise"]]);
  assert.equal(model.cards["step:draft"].ports[0].quote, "loop revise");
  assert.deepEqual(model.cards["step:summarize_check"].sections[1], { label: "aggregates", rows: ["all_hold: All policy_check With Confidence_Above 0.7"] });
});

test("loops nest: a Loop inside a For, its check and fix inside it, a For's header", () => {
  const model = modelOf(graph("ticket-triage"));
  assert.deepEqual(model.top, ["step:start", "loop:each_ticket", "step:summarize", "step:end"]);
  const each = model.frames["loop:each_ticket"];
  assert.equal(each.kind, "For");
  assert.equal(each.header, "Over tickets As ticket, At_Most 50, Collect reply Into replies");
  assert.deepEqual(each.children, ["step:classify", "step:by_tone", "step:draft", "step:escalate", "loop:revise"]);
  const revise = model.frames["loop:revise"];
  assert.equal(revise.parent, "loop:each_ticket");
  assert.equal(revise.header, "Until passed, At_Most 4, Else_Fail");
  assert.deepEqual(revise.children, ["step:check", "step:fix"]);
  assert.deepEqual(revise.ports.map((p) => [p.kind, p.target]), [["continue", "loop:each_ticket"]]);
  // The check is in the loop it serves, and the fix ends the pass: the only way back is to the loop.
  assert.deepEqual(model.cards["step:check"].ports.map((p) => [p.kind, p.target]), [["next", "step:fix"]]);
  assert.deepEqual(model.cards["step:fix"].ports.map((p) => [p.kind, p.target]), [["continue", "loop:revise"]]);
  assert.equal(model.cards["step:start"].ports[0].quote, "for each_ticket");
});

test("the source slice of a card is the lines that wrote it", () => {
  const source = "a\nb\nc\nd\n";
  assert.deepEqual(sliceOf(source, 2, 3), { text: "b\nc", first: 2 });
  assert.deepEqual(sliceOf(source, 4, null), { text: "d", first: 4 });
  assert.equal(sliceOf(source, null, null), null);
  assert.equal(sliceOf(source, 40, 41), null);
  assert.deepEqual(modelOf({ nodes: [], edges: [] }), { name: "", description: "", cards: {}, frames: {}, top: [] });
});
