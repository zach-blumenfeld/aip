'use strict';
// The tokenizer harness: the TextMate grammar run by vscode-textmate (the engine VS Code uses)
// over the example programs, asserting the scope each kind of token gets. A change to the
// grammar that stops colouring a step verb, a clause, a type, a label or a placeholder fails
// here before it reaches an editor.

const fs = require('node:fs');
const path = require('node:path');
const { test, before } = require('node:test');
const assert = require('node:assert/strict');
const vsctm = require('vscode-textmate');
const oniguruma = require('vscode-oniguruma');

const GRAMMAR = path.join(__dirname, '..', 'syntaxes', 'aip.tmLanguage.json');
const EXAMPLES = path.join(__dirname, '..', '..', '..', 'examples', 'language');

let grammar;

before(async () => {
  // onig.wasm sits beside the package's main module (release/main.js)
  const wasm = fs.readFileSync(path.join(path.dirname(require.resolve('vscode-oniguruma')), 'onig.wasm')).buffer;
  const onigLib = oniguruma.loadWASM(wasm).then(() => ({
    createOnigScanner: (patterns) => new oniguruma.OnigScanner(patterns),
    createOnigString: (s) => new oniguruma.OnigString(s),
  }));
  const registry = new vsctm.Registry({
    onigLib,
    loadGrammar: async (scopeName) => (scopeName === 'source.aip'
      ? vsctm.parseRawGrammar(fs.readFileSync(GRAMMAR, 'utf8'), GRAMMAR)
      : null),
  });
  grammar = await registry.loadGrammar('source.aip');
  assert.ok(grammar, 'the grammar loads');
});

/** Every token of `text` as {line (1-based), text, scopes}. */
function tokenize(text) {
  const tokens = [];
  let state = vsctm.INITIAL;
  text.split('\n').forEach((line, index) => {
    const result = grammar.tokenizeLine(line, state);
    for (const token of result.tokens) {
      tokens.push({ line: index + 1, text: line.slice(token.startIndex, token.endIndex), scopes: token.scopes });
    }
    state = result.ruleStack;
  });
  return tokens;
}

function example(name) {
  return fs.readFileSync(path.join(EXAMPLES, name, 'procedure.aip'), 'utf8');
}

/** The scopes of the first token on `line` whose text is `text` (surrounding spaces ignored). */
function scopesOf(tokens, line, text) {
  const token = tokens.find((t) => t.line === line && t.text.trim() === text);
  assert.ok(token, `no token ${JSON.stringify(text)} on line ${line}; tokens there: ${JSON.stringify(tokens.filter((t) => t.line === line).map((t) => t.text))}`);
  return token.scopes;
}

/** The 1-based line of the first line matching `pattern`. */
function lineOf(text, pattern) {
  const index = text.split('\n').findIndex((line) => pattern.test(line));
  assert.notEqual(index, -1, `no line matches ${pattern}`);
  return index + 1;
}

test('billing-support: step verbs, names, clauses, types, routes and comments', () => {
  const source = example('billing-support');
  const tokens = tokenize(source);
  assert.ok(scopesOf(tokens, 1, '# billing-support/procedure.aip').includes('comment.line.number-sign.aip'));

  const decide = lineOf(source, /^Decide triage/);
  assert.ok(scopesOf(tokens, decide, 'Decide').includes('keyword.control.step.aip'));
  assert.ok(scopesOf(tokens, decide, 'triage').includes('entity.name.function.step.aip'));

  const read = lineOf(source, /^\s+Read message$/);
  assert.ok(scopesOf(tokens, read, 'Read').includes('keyword.other.clause.aip'));
  assert.ok(scopesOf(tokens, read, 'message').includes('variable.other.key.aip'));

  const question = lineOf(source, /billing: true_or_false/);
  assert.ok(scopesOf(tokens, question, 'true_or_false').includes('support.type.answer.aip'));
  const choice = lineOf(source, /tone: choice \[angry, calm\]/);
  assert.ok(scopesOf(tokens, choice, 'angry').includes('constant.other.label.aip'));

  const route = lineOf(source, /^Route On by_tone/);
  assert.ok(scopesOf(tokens, route, 'Route').includes('keyword.control.step.aip'));
  assert.ok(scopesOf(tokens, route, 'On').includes('keyword.other.with.aip'));
  assert.ok(scopesOf(tokens, route, 'by_tone').includes('entity.name.function.step.aip'));
  const below = lineOf(source, /Confidence_Below 0\.6 -> escalate/);
  assert.ok(scopesOf(tokens, below, 'Confidence_Below').includes('keyword.other.clause.aip'));
  assert.ok(scopesOf(tokens, below, '0.6').includes('constant.numeric.aip'));
  assert.ok(scopesOf(tokens, below, '->').includes('keyword.operator.arrow.aip'));
  assert.ok(scopesOf(tokens, below, 'escalate').includes('entity.name.function.step.aip'));
  const arm = lineOf(source, /^\s+angry -> escalate/);
  assert.ok(scopesOf(tokens, arm, 'angry').includes('constant.other.label.aip'));

  const script = lineOf(source, /Run_Script scripts\/escalate\.py/);
  assert.ok(scopesOf(tokens, script, 'Run_Script').includes('keyword.other.clause.aip'));
  assert.ok(scopesOf(tokens, script, 'scripts/escalate.py').includes('string.unquoted.path.aip'));

  const produce = lineOf(source, /Produce ticket_id: integer/);
  assert.ok(scopesOf(tokens, produce, 'Produce').includes('keyword.other.clause.aip'));
  assert.ok(scopesOf(tokens, produce, 'ticket_id').includes('variable.other.key.aip'));
  assert.ok(scopesOf(tokens, produce, 'integer').includes('support.type.aip'));

  const next = lineOf(source, /^\s+Next_Step triage/);
  assert.ok(scopesOf(tokens, next, 'Next_Step').includes('keyword.control.flow.aip'));
  assert.ok(scopesOf(tokens, next, 'triage').includes('entity.name.function.step.aip'));

  const named = lineOf(source, /^tone_question = /);
  assert.ok(scopesOf(tokens, named, 'tone_question').includes('variable.other.constant.aip'));
  assert.ok(scopesOf(tokens, named, '=').includes('keyword.operator.assignment.aip'));
});

test('ticket-triage: loop headers and their clauses', () => {
  const source = example('ticket-triage');
  const tokens = tokenize(source);
  const forLine = lineOf(source, /^For each_ticket Over tickets/);
  assert.ok(scopesOf(tokens, forLine, 'For').includes('keyword.control.loop.aip'));
  assert.ok(scopesOf(tokens, forLine, 'each_ticket').includes('entity.name.function.loop.aip'));
  assert.ok(scopesOf(tokens, forLine, 'Over').includes('keyword.other.clause.aip'));
  assert.ok(scopesOf(tokens, forLine, 'At_Most').includes('keyword.other.clause.aip'));
  assert.ok(scopesOf(tokens, forLine, '50').includes('constant.numeric.aip'));
  const loopLine = lineOf(source, /^\s+Loop revise Until passed/);
  assert.ok(scopesOf(tokens, loopLine, 'Loop').includes('keyword.control.loop.aip'));
  assert.ok(scopesOf(tokens, loopLine, 'revise').includes('entity.name.function.loop.aip'));
  assert.ok(scopesOf(tokens, loopLine, 'Until').includes('keyword.other.clause.aip'));
  assert.ok(scopesOf(tokens, loopLine, 'Else_Fail').includes('keyword.other.clause.aip'));
});

test('dynamic-policy: a {placeholder} inside a string is an interpolation', () => {
  const source = example('dynamic-policy');
  const tokens = tokenize(source);
  const line = lineOf(source, /\{policy\}/);
  assert.ok(scopesOf(tokens, line, '{policy}').includes('variable.other.interpolation.aip'));
});

test('every example tokenizes from start to end with every character in some token', () => {
  for (const name of fs.readdirSync(EXAMPLES)) {
    const file = path.join(EXAMPLES, name, 'procedure.aip');
    if (!fs.existsSync(file)) continue;
    const source = fs.readFileSync(file, 'utf8');
    const tokens = tokenize(source);
    const rebuilt = [];
    for (const token of tokens) {
      rebuilt[token.line - 1] = (rebuilt[token.line - 1] || '') + token.text;
    }
    const lines = source.split('\n');
    lines.forEach((line, index) => {
      assert.equal(rebuilt[index] || '', line, `${name} line ${index + 1} is covered by its tokens`);
    });
  }
});
