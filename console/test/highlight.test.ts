// `npm test`: node's test runner over the page's modules that need no browser (node 22.18 or newer runs
// TypeScript as it is). Here: the TextMate tokenizer over the grammar the VS Code extension ships, on the
// example programs. The extension's own harness (editors/vscode/test/grammar.test.js) asks the same
// questions of the real engine; a token this tokenizer scopes differently is a bug here, not there.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { styleOf, tokenize, type RawGrammar, type ThemeRule, type Token } from "../src/highlight/textmate.ts";

const REPO = path.resolve(import.meta.dirname, "..", "..");
const EXAMPLES = path.join(REPO, "examples", "language");
const grammar = JSON.parse(readFileSync(path.join(REPO, "editors", "vscode", "syntaxes", "aip.tmLanguage.json"), "utf8")) as RawGrammar;
const extension = JSON.parse(readFileSync(path.join(REPO, "editors", "vscode", "package.json"), "utf8"));
const rules = extension.contributes.configurationDefaults["editor.tokenColorCustomizations"].textMateRules as ThemeRule[];

const example = (name: string) => readFileSync(path.join(EXAMPLES, name, "procedure.aip"), "utf8");

/** The 1-based line of the first line matching `pattern`. */
function lineOf(source: string, pattern: RegExp): number {
  const index = source.split("\n").findIndex((line) => pattern.test(line));
  assert.notEqual(index, -1, `no line matches ${pattern}`);
  return index + 1;
}

/** The scopes of the first token on `line` whose text is `text` (surrounding spaces ignored). */
function scopesOf(lines: Token[][], line: number, text: string): string[] {
  const token = lines[line - 1].find((t) => t.text.trim() === text);
  assert.ok(token, `no token ${JSON.stringify(text)} on line ${line}; tokens there: ${JSON.stringify(lines[line - 1].map((t) => t.text))}`);
  return token.scopes;
}

test("every example tokenizes to its own text, line for line", () => {
  for (const name of readdirSync(EXAMPLES)) {
    const source = example(name);
    const lines = tokenize(grammar, source);
    assert.deepEqual(lines.map((tokens) => tokens.map((t) => t.text).join("")), source.split("\n"), name);
    for (const tokens of lines) for (const t of tokens) assert.ok(t.text.length > 0, `${name}: an empty token`);
  }
});

test("billing-support: step verbs, names, clauses, types, routes and comments", () => {
  const source = example("billing-support");
  const lines = tokenize(grammar, source);
  assert.ok(lines[0][0].scopes.includes("comment.line.number-sign.aip"));

  const decide = lineOf(source, /^Decide triage/);
  assert.ok(scopesOf(lines, decide, "Decide").includes("keyword.control.step.aip"));
  assert.ok(scopesOf(lines, decide, "triage").includes("entity.name.function.step.aip"));
  assert.ok(lines[decide - 1].some((t) => t.scopes.includes("string.quoted.double.aip")));

  const read = lineOf(source, /^\s+Read message$/);
  assert.ok(scopesOf(lines, read, "Read").includes("keyword.other.clause.aip"));
  assert.ok(scopesOf(lines, read, "message").includes("variable.other.key.aip"));

  const check = lineOf(source, /Confidence_Below/);
  assert.ok(scopesOf(lines, check, "Confidence_Below").includes("keyword.other.clause.aip"));
  assert.ok(scopesOf(lines, check, "0.9").includes("constant.numeric.aip"));
  assert.ok(scopesOf(lines, check, "->").includes("keyword.operator.arrow.aip"));
  assert.ok(scopesOf(lines, check, "escalate").includes("entity.name.function.step.aip"));

  const tone = lineOf(source, /tone:\s+choice/);
  assert.ok(scopesOf(lines, tone, "choice").includes("support.type.answer.aip"));
  assert.ok(scopesOf(lines, tone, "angry").includes("constant.other.label.aip"));

  const member = lineOf(source, /Read triage_decision\.tone$/);
  assert.ok(scopesOf(lines, member, "tone").includes("variable.other.member.aip"));
  const script = lineOf(source, /Run_Script/);
  assert.ok(scopesOf(lines, script, "scripts/escalate.py").includes("string.unquoted.path.aip"));
});

test("fixed-policy: a loop header, a triple-quoted string across lines, an aggregation", () => {
  const source = example("fixed-policy");
  const lines = tokenize(grammar, source);
  const loop = lineOf(source, /^Loop revise/);
  assert.ok(scopesOf(lines, loop, "Loop").includes("keyword.control.loop.aip"));
  assert.ok(scopesOf(lines, loop, "revise").includes("entity.name.function.loop.aip"));
  assert.ok(scopesOf(lines, loop, "Until").includes("keyword.other.clause.aip"));
  assert.ok(scopesOf(lines, loop, "3").includes("constant.numeric.aip"));

  // The approved claims sit inside policy_claims' triple quotes, several lines down from where it opened.
  const claim = lineOf(source, /^- A duplicate charge/);
  assert.ok(lines[claim - 1].every((t) => t.scopes.includes("string.quoted.triple.aip")));
  // The string closed: the next named string is a name again.
  const after = lineOf(source, /^policy_tone/);
  assert.ok(scopesOf(lines, after, "policy_tone").includes("variable.other.constant.aip"));

  const aggregation = lineOf(source, /all_hold: All/);
  assert.ok(scopesOf(lines, aggregation, "All").includes("keyword.other.aggregate.aip"));
  assert.ok(scopesOf(lines, aggregation, "0.7").includes("constant.numeric.aip"));
});

test("dynamic-policy: a placeholder in a named string is its own token", () => {
  const source = example("dynamic-policy");
  const lines = tokenize(grammar, source);
  const line = lineOf(source, /^\{policy\}$/);
  assert.deepEqual(lines[line - 1].map((t) => t.text), ["{policy}"]);
  assert.ok(lines[line - 1][0].scopes.includes("variable.other.interpolation.aip"));
});

test("a token takes the extension's colour for the longest scope prefix that names it", () => {
  assert.deepEqual(styleOf(rules, ["source.aip", "keyword.control.step.aip"]), { color: "#FF7AB2", bold: true, italic: false });
  assert.equal(styleOf(rules, ["source.aip", "keyword.other.clause.aip"]).color, "#6CB6FF");
  assert.equal(styleOf(rules, ["source.aip", "string.quoted.triple.aip", "variable.other.interpolation.aip"]).italic, true);
  // A scope no rule names takes the nearest enclosing scope's rule, or nothing.
  assert.deepEqual(styleOf(rules, ["source.aip", "punctuation.definition.block.aip"]), {});
  const base: ThemeRule[] = [{ scope: "string", settings: { foreground: "#111111" } }, { scope: "string.quoted.triple", settings: { foreground: "#222222" } }];
  assert.equal(styleOf(base, ["source.aip", "string.quoted.triple.aip"]).color, "#222222");
  assert.equal(styleOf(base, ["source.aip", "string.quoted.double.aip", "constant.character.escape.aip"]).color, "#111111");
});
