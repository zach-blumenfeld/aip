// The run console's human-step picker (plan C5): which Task_Agent steps a person answers, and the rows a list
// answer is ticked from; and the Studio's word on each script, from the reviews.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { Graph } from "../src/graph/bundle.ts";
import { candidatesOf, rowText } from "../src/run/answers.ts";
import { agentSteps, forAPerson, PERSON_MARKER } from "../src/run/human.ts";
import { scriptNotes } from "../src/studio/chat.ts";

const graph = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.graph.json`, import.meta.url), "utf8")) as Graph;

test("a task is a person's when its prompt opens with the drafter's marker or its description says so", () => {
  assert.equal(forAPerson("Approve it.", `${PERSON_MARKER}: approve the refund.`), true);
  assert.equal(forAPerson(`${PERSON_MARKER}: approve the refund.`, `${PERSON_MARKER}: approve the refund.`), true);
  assert.equal(forAPerson("A person answers the questions the rules leave open.", "# Ask\n..."), true);
  assert.equal(forAPerson("Summarize the request for the approver.", "Summarize the request for the approver."), false);
  assert.equal(forAPerson("Draft a reply.", "Mention a personal touch."), false);
});

test("the Task_Agent steps of a graph, in written order, with the prompt a Prompt file gives", () => {
  const g = graph("billing-support-agent");
  const steps = agentSteps(g);
  assert.deepEqual(steps.map((s) => s.name), ["triage", "reply"]);
  // The compiler's graph has no file text: the description stands in for the prompt.
  assert.equal(steps[1].prompt, steps[1].description);
  assert.deepEqual(steps.map((s) => s.person), [false, false]);
  // The server's does: a Prompt file that opens with the marker makes the step a person's.
  const file = g.nodes.find((n) => n.labels.includes("File") && n.properties.path === "assets/reply.md")!;
  const served: Graph = { ...g, nodes: g.nodes.map((n) => (n === file ? { ...n, properties: { ...n.properties, text: `${PERSON_MARKER}: write the reply.` } } : n)) };
  assert.deepEqual(agentSteps(served).map((s) => [s.name, s.person]), [["triage", false], ["reply", true]]);
  assert.deepEqual(agentSteps(graph("billing-support")).map((s) => s.name), ["reply"]);
});

test("a list answer is ticked from the one list the task reads", () => {
  assert.deepEqual(candidatesOf("list", { folders: [{ path: "a" }, { path: "b" }], why: "x" }), [{ path: "a" }, { path: "b" }]);
  assert.equal(candidatesOf("list", { a: [1], b: [2] }), null);
  assert.equal(candidatesOf("list", { a: [] }), null);
  assert.equal(candidatesOf("string", { a: [1] }), null);
  assert.equal(rowText("x"), "x");
  assert.equal(rowText({ path: "docs/a.md", size: 3 }), "docs/a.md");
  assert.equal(rowText({ n: 1 }), '{"n":1}');
});

test("what the reviews say each script touches: the last line naming it", () => {
  const reviews = [
    "It covers refunds.\nScripts:\nscripts/check.py: approves everything; uses no credentials.",
    "Changed it.\nScripts:\ncheck.py - now reads the amount; touches nothing outside the working directory.",
  ];
  assert.deepEqual(scriptNotes(reviews, ["scripts/check.py", "scripts/other.py"]),
                   { "scripts/check.py": "now reads the amount; touches nothing outside the working directory." });
  assert.deepEqual(scriptNotes(reviews.slice(0, 1), ["scripts/check.py"]), { "scripts/check.py": "approves everything; uses no credentials." });
});
