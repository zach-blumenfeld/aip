// How the step graph says a step's kind (graph/kinds.ts): words a person reads and a glyph, for every kind the
// compiler writes into a bundle's graph, read off the fixtures the real compiler wrote.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { kindLook, loopWords, wordsWidth } from "../src/graph/kinds.ts";

const fixtures = new URL("./fixtures/", import.meta.url);
const graphs = readdirSync(fixtures).filter((f) => f.endsWith(".graph.json"))
  .map((f) => JSON.parse(readFileSync(new URL(f, fixtures), "utf8")) as { nodes: { labels: string[]; properties: Record<string, unknown> }[] });

test("every step kind in the examples has words and a glyph, and the words are not the keyword", () => {
  const kinds = new Set(graphs.flatMap((g) => g.nodes.filter((n) => n.labels.includes("Step")).map((n) => String(n.properties.kind))));
  assert.deepEqual([...kinds].sort(), ["Aggregate", "Decide", "End", "Execute", "Route", "Start", "Task_Agent"]);
  for (const kind of kinds) {
    const look = kindLook(kind);
    assert.ok(look.icon.startsWith("M"), `${kind} has a glyph`);
    assert.notEqual(look.words, kind);
    assert.equal(look.words, look.words.toLowerCase(), `${kind} is said in plain words`);
    assert.ok(wordsWidth(look.words) < 112, `${kind}'s words fit the node beside the glyph`);
  }
  assert.equal(kindLook("Decide").words, "model decides");
  assert.equal(kindLook("Execute").words, "runs a script");
  assert.equal(kindLook("Task_Agent").words, "agent task");
});

test("a kind the console does not know is shown by its keyword, with no glyph", () => {
  assert.deepEqual(kindLook("Wait"), { words: "Wait", icon: "" });
});

test("a loop is said by how it repeats", () => {
  assert.equal(loopWords("For", "Over"), "for each item");
  assert.equal(loopWords("Loop", "Until"), "repeats until");
  assert.equal(loopWords("Loop", "Times"), "repeats");
  assert.equal(loopWords("For"), "for each item");
  assert.equal(loopWords("Loop", "Until_passed"), "repeats until");
});
