'use strict';
// The diagnostics side of the extension against the real compiler: `aip compile --check --json
// --stdin` on a fixture with one error, the buffer winning over the disk, a syntax error's
// empty span, a missing command, the version line. The compiler is `aip` on PATH, or the words
// in AIP_COMMAND; from a checkout, `uv run aip` finds the workspace from the fixture's folder.

const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { check, version, parseVersion, splitCommand, toRange, toDiagnostics, debounce } = require('../src/compiler');

const AIP = process.env.AIP_COMMAND || 'uv run aip';
const FIXTURE = path.join(__dirname, 'fixtures', 'one-error', 'procedure.aip');

test('the fixture with one error gives one diagnostic at its line and column', async () => {
  const result = await check({ command: AIP, file: FIXTURE, source: fs.readFileSync(FIXTURE, 'utf8') });
  assert.equal(result.status, 'report', JSON.stringify(result));
  assert.equal(result.code, 1);
  assert.equal(result.report.ok, false);
  const diagnostics = toDiagnostics(result.report);
  assert.equal(diagnostics.length, 1);
  const [one] = diagnostics;
  assert.deepEqual(one.range, { start: { line: 11, character: 7 }, end: { line: 11, character: 13 } });
  assert.equal(one.severity, 'error');
  assert.equal(one.code, 'unknown_key');
  assert.equal(one.step, 'end');
  assert.match(one.message, /messag/);
});

test('the buffer is what is checked, not the file on disk', async () => {
  const fixed = fs.readFileSync(FIXTURE, 'utf8').replace('Read messag', 'Read message');
  const result = await check({ command: AIP, file: FIXTURE, source: fixed });
  assert.equal(result.status, 'report', JSON.stringify(result));
  assert.equal(result.code, 0);
  assert.equal(result.report.ok, true);
  assert.deepEqual(toDiagnostics(result.report), []);
  assert.equal(result.report.procedure, 'one_error');
  assert.ok(Array.isArray(result.report.graph.nodes), 'the report carries the graph for the preview');
});

test('a syntax error at the end of the file still gets a one-character range', async () => {
  const result = await check({ command: AIP, file: FIXTURE, source: 'Procedure p "x"\nStart "s" {\n  m: string\n' });
  assert.equal(result.status, 'report', JSON.stringify(result));
  const [one] = toDiagnostics(result.report);
  assert.equal(one.code, 'syntax_error');
  assert.equal(one.range.end.character, one.range.start.character + 1);
  assert.equal(one.range.end.line, one.range.start.line);
});

test('a command that does not exist is reported as not found', async () => {
  const result = await check({ command: 'aip-is-not-installed-here-5f3a', file: FIXTURE, source: '' });
  assert.equal(result.status, 'not-found');
  assert.equal((await version({ command: 'aip-is-not-installed-here-5f3a' })).status, 'not-found');
  assert.equal((await version({ command: '   ' })).status, 'not-found');
});

test('a command that answers without a report is a failure, not a crash', async () => {
  const result = await check({ command: `"${process.execPath}" -e process.exit(4)`, file: FIXTURE, source: '' });
  assert.equal(result.status, 'failed');
  assert.equal(result.code, 4);
  assert.match(result.error, /without a JSON report/);
});

test('the version line names the language version', async () => {
  const result = await version({ command: AIP });
  assert.equal(result.status, 'version', JSON.stringify(result));
  assert.match(result.aip, /^\d+\.\d+/);
  assert.equal(result.language, '0.9');
  assert.equal(result.line, `aip ${result.aip} language 0.9`);
});

test('parseVersion tells the 0.9 language from the 0.8 format', () => {
  assert.deepEqual(parseVersion('aip 0.9.0 language 0.9\n'), { aip: '0.9.0', language: '0.9', line: 'aip 0.9.0 language 0.9' });
  assert.deepEqual(parseVersion('aip 0.8.0 format 0.8'), { aip: '0.8.0', language: null, format: '0.8', line: 'aip 0.8.0 format 0.8' });
  assert.equal(parseVersion('usage: aip <command>'), null);
  assert.equal(parseVersion(''), null);
});

test('splitCommand', () => {
  assert.deepEqual(splitCommand('aip'), ['aip']);
  assert.deepEqual(splitCommand('  uv run   aip '), ['uv', 'run', 'aip']);
  assert.deepEqual(splitCommand('"/Applications/my tools/aip" --flag'), ['/Applications/my tools/aip', '--flag']);
  assert.deepEqual(splitCommand("'a b' c"), ['a b', 'c']);
  assert.deepEqual(splitCommand(''), []);
  assert.deepEqual(splitCommand(undefined), []);
});

test('toRange: 1-based inclusive start and exclusive end become 0-based; an empty span widens', () => {
  assert.deepEqual(toRange({ line: 12, column: 8, end_line: 12, end_column: 14 }),
    { start: { line: 11, character: 7 }, end: { line: 11, character: 13 } });
  assert.deepEqual(toRange({ line: 7, column: 1, end_line: 7, end_column: 1 }),
    { start: { line: 6, character: 0 }, end: { line: 6, character: 1 } });
  assert.deepEqual(toRange({ line: 3, column: 5, end_line: 5, end_column: 2 }),
    { start: { line: 2, character: 4 }, end: { line: 4, character: 1 } });
  assert.deepEqual(toRange({ line: 2, column: 3 }), { start: { line: 1, character: 2 }, end: { line: 1, character: 3 } });
  assert.deepEqual(toRange({}), { start: { line: 0, character: 0 }, end: { line: 0, character: 1 } });
});

test('toDiagnostics keeps code, severity, message and step, and defaults an unknown severity to info', () => {
  const report = { diagnostics: [
    { code: 'unknown_key', severity: 'error', message: 'm', line: 1, column: 1, end_line: 1, end_column: 2, step: 's' },
    { code: 'odd', severity: 'fatal', message: 'n', line: 2, column: 1, end_line: 2, end_column: 1 },
  ] };
  const [a, b] = toDiagnostics(report);
  assert.deepEqual(a, { range: toRange(report.diagnostics[0]), severity: 'error', message: 'm', code: 'unknown_key', step: 's' });
  assert.deepEqual(b, { range: toRange(report.diagnostics[1]), severity: 'info', message: 'n', code: 'odd', step: null });
  assert.deepEqual(toDiagnostics({}), []);
});

test('debounce runs once after the quiet period, with the last arguments, and cancel drops it', async () => {
  const calls = [];
  const debounced = debounce((x) => calls.push(x), 20);
  debounced(1);
  debounced(2);
  debounced(3);
  await new Promise((r) => setTimeout(r, 60));
  assert.deepEqual(calls, [3]);
  debounced(4);
  debounced.cancel();
  await new Promise((r) => setTimeout(r, 60));
  assert.deepEqual(calls, [3]);
});
