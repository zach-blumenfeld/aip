// The run console's human-step picker (plan C5): which Task_Agent steps a person answers, and the rows a list
// answer is ticked from; and the Studio's word on each script, from the reviews.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { Graph } from "../src/graph/bundle.ts";
import { candidatesOf, rowText } from "../src/run/answers.ts";
import { agentSteps } from "../src/run/human.ts";
import { scriptNotes } from "../src/studio/chat.ts";

const graph = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.graph.json`, import.meta.url), "utf8")) as Graph;

test("the Task_Agent steps of a graph, in written order, each a person's when aip's human_steps names it", () => {
  const g = graph("billing-support-agent");
  assert.deepEqual(agentSteps(g).map((s) => [s.name, s.person]), [["triage", false], ["reply", false]]);
  // Which steps are a person's is aip's rule (aip.model.answerer.human_steps); the page reads its answer.
  assert.deepEqual(agentSteps(g, ["reply"]).map((s) => [s.name, s.person]), [["triage", false], ["reply", true]]);
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
