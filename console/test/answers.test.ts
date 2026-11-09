// A form's fields as the JSON the CLI expects: the inputs of `aip run`, the answers of `aip resume`.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { Task } from "../src/api/types.ts";
import { answersFor, coerce, collect, fieldKind, fieldText, optionsOf, passLabel } from "../src/run/answers.ts";

test("how a key is asked for follows its type and its labels", () => {
  assert.equal(fieldKind("string"), "text");
  assert.equal(fieldKind("true_or_false"), "pick");
  assert.equal(fieldKind("choice", ["angry", "calm"]), "pick");
  assert.equal(fieldKind("score", ["low", "high"]), "pick");
  assert.equal(fieldKind("integer"), "number");
  assert.equal(fieldKind("list"), "json");
  assert.equal(fieldKind(null), "json");
  assert.deepEqual(optionsOf("true_or_false"), ["true", "false"]);
  assert.deepEqual(optionsOf("choice", ["angry", "calm"]), ["angry", "calm"]);
  assert.deepEqual(optionsOf("string"), []);
});

test("a field's text becomes the value of its type, or says what is wrong", () => {
  assert.equal(coerce("true", "true_or_false"), true);
  assert.equal(coerce("false", "true_or_false"), false);
  assert.equal(coerce("calm", "choice", ["angry", "calm"]), "calm");
  assert.throws(() => coerce("", "choice", ["angry", "calm"]), /pick one/);
  assert.throws(() => coerce("furious", "choice", ["angry", "calm"]), /one of angry, calm/);
  assert.equal(coerce("  kept as typed ", "string"), "  kept as typed ");
  assert.equal(coerce(undefined, "string"), "");
  assert.equal(coerce("42", "integer"), 42);
  assert.equal(coerce("0.5", "float"), 0.5);
  assert.throws(() => coerce("4.2", "integer"), /whole number/);
  assert.throws(() => coerce("", "float"), /expected a number/);
  assert.deepEqual(coerce('["a", "b"]', "list"), ["a", "b"]);
  assert.throws(() => coerce("not json", "list"), /not JSON/);
  assert.throws(() => coerce("", "object"), /expected JSON/);
});

test("a form's first state is the example's values, placeholders left blank", () => {
  assert.equal(fieldText("<string>", "string"), "");
  assert.equal(fieldText("hello", "string"), "hello");
  assert.equal(fieldText([], "list"), "[]");
  assert.equal(fieldText(undefined, "string"), "");
  assert.equal(fieldText(3, "integer"), "3");
});

test("a form is collected whole, naming every key that would not go", () => {
  const types = { message: "string", tickets: "list", tone: "choice" };
  const labels = { tone: ["angry", "calm"] };
  assert.deepEqual(collect({ message: "hi", tickets: "[1]", tone: "calm" }, types, labels),
                   { value: { message: "hi", tickets: [1], tone: "calm" }, problems: {} });
  const bad = collect({ message: "hi", tickets: "oops" }, types, labels);
  assert.deepEqual(Object.keys(bad.problems).sort(), ["tickets", "tone"]);
  assert.deepEqual(bad.value, { message: "hi" });
});

test("one task is answered with its object; several, together, keyed by index", () => {
  const task = (index: number, pass: number | null): Task =>
    ({ index, pass, passes: pass === null ? [] : [{ loop: "each_ticket", pass }], prompt: "", state: {}, references: [], answer_with: { reply: "string" }, labels: {} });
  assert.deepEqual(answersFor([task(0, null)], { 0: { reply: "a" } }), { reply: "a" });
  assert.deepEqual(answersFor([task(0, 0), task(1, 2)], { 0: { reply: "a" }, 1: { reply: "b" } }), { "0": { reply: "a" }, "1": { reply: "b" } });
  assert.equal(passLabel(task(1, 2).passes), "each_ticket 2");
  assert.equal(passLabel([{ loop: "revise", pass: 1 }, { loop: "review", pass: 0 }]), "revise 1 / review 0");
  assert.equal(passLabel([]), "");
});
