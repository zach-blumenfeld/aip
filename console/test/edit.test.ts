// The Studio's edits (src/canvas/edit.ts) and the diagnostics drawn on cards (src/canvas/problems.ts), on
// the examples' own source and the graphs `aip compile --json` printed for them (test/fixtures). Each edit
// is checked as the text it makes; the e2e spec (e2e/studio.spec.ts) checks that the compiler and the
// formatter agree with it.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import {
  addBranch, addCard, addOutput, addRead, applyEdits, connect, disconnect, move, nameFor, removeItem, removeOutput, removeRead,
  setBound, setText, targetsFor, unrouted, upstreamOf,
} from "../src/canvas/edit.ts";
import { modelOf, type Graph } from "../src/canvas/model.ts";
import { withProblems } from "../src/canvas/problems.ts";

const graph = (name: string) => JSON.parse(readFileSync(path.join(import.meta.dirname, "fixtures", `${name}.graph.json`), "utf8")) as Graph;
const source = (name: string) => readFileSync(path.join(import.meta.dirname, "..", "..", "examples", "language", name, "procedure.aip"), "utf8");
const edge = (g: Graph, type: string, start: string, value?: string) =>
  g.edges.find((e) => e.type === type && e.start === start && (value === undefined || e.properties.value === value))!;

const BILLING = source("billing-support"), TRIAGE = source("ticket-triage");
const billing = graph("billing-support"), triage = graph("ticket-triage");

test("edits apply against the text as it was, last first", () => {
  assert.equal(applyEdits("ab\ncd\n", [{ line: 1, column: 2, endLine: 2, endColumn: 2, text: "X" }, { line: 1, column: 1, endLine: 1, endColumn: 1, text: ">" }]), ">aXd\n");
});

test("a new card is a block of its kind after the card picked, named from its description", () => {
  const { edits, name } = addCard(BILLING, billing, { kind: "Task_Agent", description: "Review the drafted reply before it is sent.", after: "step:by_tone", next: "reply" });
  assert.equal(name, "review_drafted_reply");
  const out = applyEdits(BILLING, edits);
  assert.ok(out.includes('  calm  -> reply\n}\n\nTask_Agent review_drafted_reply "Review the drafted reply before it is sent." {\n  Next_Step reply\n}\n\nExecute escalate'), out);
  assert.equal(nameFor("Reply", billing), "reply_2", "a taken name gets a number");
  assert.equal(nameFor("!!!", billing), "step");

  const decide = applyEdits(BILLING, addCard(BILLING, billing, { kind: "Decide", description: "Is it urgent?", after: "step:triage", next: "by_tone" }).edits);
  assert.ok(decide.includes('Decide urgent "Is it urgent?" {\n  Answer_Questions {\n    answer: true_or_false "Is it urgent?"\n  }\n  Produce urgent\n  Next_Step by_tone\n}'));
  const route = applyEdits(BILLING, addCard(BILLING, billing, { kind: "Route", description: "By billing", after: "step:triage", next: "end", answer: "triage_decision.billing", labels: ["true", "false"] }).edits);
  assert.ok(route.includes('Route billing "By billing" {\n  Read triage_decision.billing\n  true -> end\n  false -> end\n}'));
  const inLoop = applyEdits(TRIAGE, addCard(TRIAGE, triage, { kind: "Execute", description: "Log it", after: "step:draft", next: "Continue", script: "scripts/escalate.py" }).edits);
  assert.ok(inLoop.includes('  }\n\n  Execute log "Log it" {\n    Run_Script scripts/escalate.py\n    Next_Step Continue\n  }\n\n  Execute escalate'), "inside the body, at its indent");
});

test("a card or a loop is removed whole, with the blank line after it", () => {
  const out = applyEdits(BILLING, removeItem(BILLING, billing, "step:escalate"));
  assert.ok(out.includes("  calm  -> reply\n}\n\nTask_Agent With reply"));
  assert.ok(!out.includes("Execute escalate"));
  assert.throws(() => removeItem(BILLING, billing, "step:start"), /one Start/);
  const loop = applyEdits(TRIAGE, removeItem(TRIAGE, triage, "loop:revise"));
  assert.ok(loop.includes("    Continue\n  }\n\n  Next_Step summarize\n}"), loop);
});

test("connecting a port rewrites its target; disconnecting takes its line away", () => {
  assert.ok(applyEdits(BILLING, connect(BILLING, edge(billing, "BRANCH", "step:by_tone", "calm"), "escalate")).includes("  calm  -> escalate\n"));
  assert.ok(applyEdits(BILLING, connect(BILLING, edge(billing, "NEXT", "step:triage"), "end")).includes("  Produce triage_decision\n  Next_Step end\n"));
  assert.ok(applyEdits(BILLING, connect(BILLING, edge(billing, "BELOW", "step:by_tone"), "reply")).includes("Confidence_Below 0.9 -> reply\n"));
  // A step's `Continue` becomes a Next_Step, and back.
  const fix = edge(triage, "CONTINUES", "step:fix");
  assert.ok(applyEdits(TRIAGE, connect(TRIAGE, fix, "check")).includes("      Produce reply: string\n      Next_Step check\n    }"));
  assert.ok(applyEdits(TRIAGE, connect(TRIAGE, edge(triage, "NEXT", "step:check"), "Continue")).includes("      Produce passed: true_or_false\n      Continue\n"));
  const cut = applyEdits(BILLING, disconnect(BILLING, edge(billing, "BRANCH", "step:by_tone", "calm")));
  assert.ok(cut.includes("  angry -> escalate\n}\n"));
});

test("a branch for a value the route does not name yet, and its check", () => {
  const without = applyEdits(BILLING, disconnect(BILLING, edge(billing, "BRANCH", "step:by_tone", "calm")));
  assert.deepEqual(unrouted(billing, "step:by_tone"), { labels: [], checked: true });
  assert.ok(applyEdits(BILLING, addBranch(BILLING, billing, "step:by_tone", "calm", "end")).includes("  calm  -> reply\n  calm -> end\n}"));
  assert.ok(applyEdits(BILLING, addBranch(BILLING, billing, "step:by_tone", null, "reply", 0.7)).includes("  Confidence_Below 0.7 -> reply\n}"));
  assert.ok(without.length < BILLING.length);
});

test("bounds: a route's check and a loop's cap", () => {
  assert.ok(applyEdits(BILLING, setBound(BILLING, billing, "step:by_tone", 0.75)).includes("Confidence_Below 0.75 -> escalate"));
  assert.ok(applyEdits(TRIAGE, setBound(TRIAGE, triage, "loop:revise", 6)).includes("Loop revise Until passed, At_Most 6, Else_Fail {"));
  assert.ok(applyEdits(TRIAGE, setBound(TRIAGE, triage, "loop:each_ticket", 20)).includes("At_Most 20"));
  assert.throws(() => setBound(BILLING, billing, "step:reply", 1), /no bound/);
});

test("reads: added after the last, removed with their comma, the line going with the last", () => {
  assert.ok(applyEdits(BILLING, addRead(BILLING, billing, "step:reply", "ticket_id")).includes("  Read message, triage_decision.tone, ticket_id\n"));
  assert.ok(applyEdits(BILLING, removeRead(BILLING, billing, "step:escalate", "message")).includes("  Read triage_decision.tone\n  Run_Script"));
  assert.ok(applyEdits(BILLING, removeRead(BILLING, billing, "step:escalate", "triage_decision.tone")).includes("  Read message\n  Run_Script"));
  const none = applyEdits(BILLING, removeRead(BILLING, billing, "step:triage", "message"));
  assert.ok(none.includes('Decide triage "Classify whether the message is about billing and how upset the customer is." {\n  Answer_Questions {'));
  const back = applyEdits(BILLING, addRead(BILLING, billing, "step:start", "x"));
  assert.ok(back.includes('Start "The customer\'s message, as support received it." {\n  Read x\n  message:'), "the line after the header");
});

test("outputs: a Produce line, a continuation, an input of Start", () => {
  assert.ok(applyEdits(BILLING, addOutput(BILLING, billing, "step:reply", { name: "subject", type: "string", description: "A subject line." }))
    .includes('  Produce reply: string "The drafted reply to send the customer."\n          subject: string "A subject line."\n  Next_Step end'));
  assert.ok(applyEdits(BILLING, addOutput(BILLING, billing, "step:start", { name: "plan", type: "string" })).includes('  plan: string\n  Next_Step triage'));
  assert.ok(applyEdits(BILLING, removeOutput(BILLING, billing, "step:escalate", "ticket_id")).includes('  Produce queue:     string  "The queue the ticket was routed to."\n  Next_Step end'));
  assert.ok(applyEdits(BILLING, removeOutput(BILLING, billing, "step:reply", "reply")).includes("  Use assets/policy.md, references/help.md help_reference\n  Next_Step end"));
  assert.throws(() => addOutput(BILLING, billing, "step:triage", { name: "x", type: "string" }), /one key/);
});

test("descriptions, the procedure's, and a question's instruction, through a named string when it is one", () => {
  assert.ok(applyEdits(BILLING, setText(BILLING, billing, "step:reply", 'Draft a "kind" reply.')).includes('Task_Agent With reply "Draft a \\"kind\\" reply." {'));
  assert.ok(applyEdits(BILLING, setText(BILLING, billing, "question:triage.billing", "About money?")).includes('billing: true_or_false "About money?"'));
  const named = applyEdits(BILLING, setText(BILLING, billing, "question:triage.tone", "Upset?"));
  assert.ok(named.includes('tone_question  = "Upset?"') && named.includes("choice [angry, calm] tone_question"));
  assert.ok(applyEdits(BILLING, setText(BILLING, billing, "procedure", "Triage billing.")).includes('Procedure billing_support\n  "Triage billing."\n'));
});

test("moving a card into a loop and out of it", () => {
  const into = applyEdits(TRIAGE, move(TRIAGE, triage, "step:summarize", "loop:revise"));
  assert.ok(into.includes("      Continue\n    }\n\nTask_Agent summarize"), into);
  assert.ok(!/\n\nTask_Agent summarize[^]*End/.test(into.slice(into.indexOf("Next_Step summarize"))), "it left the top");
  const out = applyEdits(TRIAGE, move(TRIAGE, triage, "step:fix", null));
  assert.ok(out.includes("    Continue\n  }\n\n    Task_Agent fix"), "after the loop it was in");
  assert.throws(() => move(TRIAGE, triage, "step:fix", "loop:revise"), /already/);
  assert.throws(() => move(TRIAGE, triage, "loop:each_ticket", "loop:revise"), /itself/);
});

test("what a card offers: keys upstream, a route's values, where a port may lead", () => {
  const keys = upstreamOf(billing, "step:reply").map((o) => o.key);
  assert.deepEqual(keys.sort(), ["message", "triage_decision", "triage_decision.billing", "triage_decision.tone"]);
  assert.deepEqual(upstreamOf(billing, "step:by_tone").find((o) => o.key === "triage_decision.tone")?.labels, ["angry", "calm"]);
  const inBody = upstreamOf(triage, "step:fix").map((o) => o.key);
  for (const k of ["ticket", "policy", "passed", "classification.tone"]) assert.ok(inBody.includes(k), k);
  assert.deepEqual(targetsFor(billing, "step:triage"), ["triage", "by_tone", "escalate", "reply", "end"].filter((n) => n !== "triage"));
  assert.ok(targetsFor(triage, "step:fix").includes("Continue") && !targetsFor(triage, "step:fix").includes("end"));
  assert.ok(targetsFor(triage, "loop:revise").includes("draft"), "a loop's exit leads within the block it is in");
});

test("problems land on their card: messages, a red port, a missing way out drawn as one", () => {
  const model = modelOf(billing);
  const { model: marked, loose } = withProblems(model, [
    { code: "missing_branch", severity: "error", message: "Route by_tone has no branch for calm and other; a route names every value", line: 48, step: "by_tone" },
    { code: "unknown_step", severity: "error", message: "nowhere", line: 51, step: "by_tone" },
    { code: "missing_next_step", severity: "error", message: "Task_Agent reply does not say where it goes", line: 64, step: "reply" },
    { code: "unused_name", severity: "info", message: "x is unused", line: 1, step: null },
  ]);
  const route = marked.cards["step:by_tone"];
  assert.equal(route.problems?.length, 2);
  assert.deepEqual(route.ports.filter((p) => p.target === "").map((p) => p.label), ["calm", "other"]);
  assert.equal(route.ports.find((p) => p.label === "angry")?.problem, "nowhere");
  assert.equal(marked.cards["step:reply"].ports.at(-1)?.quote, "nowhere yet");
  assert.equal(marked.cards["step:reply"].sections.at(-1)?.label, "problems");
  assert.deepEqual(loose.map((p) => p.code), ["unused_name"]);
  assert.equal(model.cards["step:by_tone"].problems, undefined, "the model drawn without problems is untouched");
});
