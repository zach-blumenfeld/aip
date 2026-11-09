'use strict';
/**
 * The extension's side of the compiler: run `aip compile --check --json --stdin` on the text of
 * a buffer, turn the report's diagnostics into editor ranges, read `aip --version`. Nothing here
 * imports the `vscode` module, so `node --test` covers it against the real compiler
 * (test/compiler.test.js); extension.js is the thin layer that wires it to the editor.
 *
 * The compiler's diagnostic shape is the plan's L2: `{code, severity, message, file, line,
 * column, end_line, end_column, step}`, lines and columns 1-based, `end_column` the column after
 * the last character. A syntax error may carry an empty span, at the end of the file included.
 */

const { spawn } = require('node:child_process');
const path = require('node:path');

/** Shown in the status bar's tooltip and on the version command when `aip` is not found. */
const INSTALL_HINT =
  'The aip command was not found. Install it with `uv tool install "agent-instruction-protocol[server]"` ' +
  '(see https://github.com/zach-blumenfeld/aip#install), or point the setting "aip.command" at it.';

const SEVERITIES = ['error', 'warning', 'info'];

/** `aip` or `uv run aip` or `"/path with spaces/aip"` into the words to spawn. */
function splitCommand(command) {
  const words = [];
  let current = '';
  let quote = null;
  let quoted = false;
  for (const ch of String(command || '')) {
    if (quote) {
      if (ch === quote) quote = null;
      else current += ch;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      quoted = true;
    } else if (/\s/.test(ch)) {
      if (current || quoted) words.push(current);
      current = '';
      quoted = false;
    } else {
      current += ch;
    }
  }
  if (current || quoted) words.push(current);
  return words;
}

/**
 * Spawn the command with `args` appended, feed it `input`, collect its output.
 * Resolves (never rejects) to one of:
 *   {status: 'exited', code, stdout, stderr}
 *   {status: 'not-found', error}          the executable does not exist
 *   {status: 'failed', error, stdout, stderr}   it could not be started or did not finish in time
 */
function run(command, args, { cwd, input, timeoutMs = 30000 } = {}) {
  return new Promise((resolve) => {
    const [executable, ...leading] = splitCommand(command);
    if (!executable) {
      resolve({ status: 'not-found', error: 'the aip command is empty' });
      return;
    }
    let child;
    try {
      child = spawn(executable, [...leading, ...args], { cwd, windowsHide: true });
    } catch (error) {
      resolve({ status: 'not-found', error: error.message });
      return;
    }
    let stdout = '';
    let stderr = '';
    let settled = false;
    const settle = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const timer = setTimeout(() => {
      child.kill();
      settle({ status: 'failed', error: `aip did not answer within ${timeoutMs} ms`, stdout, stderr });
    }, timeoutMs);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => {
      if (error.code === 'ENOENT') settle({ status: 'not-found', error: error.message });
      else settle({ status: 'failed', error: error.message, stdout, stderr });
    });
    child.on('close', (code) => settle({ status: 'exited', code, stdout, stderr }));
    child.stdin.on('error', () => { /* the process may exit before reading; 'close' reports it */ });
    child.stdin.end(input === undefined ? '' : input);
  });
}

/**
 * Check a buffer: `source` is the text of `file` (a procedure.aip, saved or not); the compiler
 * reads the folder's other files from disk. Resolves to `{status: 'report', report, code}` when
 * the compiler answered with its JSON report (code 0 clean, 1 with errors), or to a `not-found`
 * or `failed` result as `run` gives them.
 */
async function check({ command = 'aip', file, source, timeoutMs } = {}) {
  const result = await run(command, ['compile', '--check', '--json', '--stdin', file], {
    cwd: path.dirname(file), input: source, timeoutMs,
  });
  if (result.status !== 'exited') return result;
  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch {
    return { status: 'failed', error: `aip compile exited ${result.code} without a JSON report`,
      stdout: result.stdout, stderr: result.stderr, code: result.code };
  }
  if (!report || !Array.isArray(report.diagnostics)) {
    return { status: 'failed', error: 'the compiler\'s report has no diagnostics list',
      stdout: result.stdout, stderr: result.stderr, code: result.code };
  }
  return { status: 'report', report, code: result.code, stderr: result.stderr };
}

/** `aip 0.9.0 language 0.9` → {aip: '0.9.0', language: '0.9'}; the 0.8 runtime's `aip 0.8.0 format 0.8`
 * → {aip: '0.8.0', language: null, format: '0.8'}; anything else → null. */
function parseVersion(text) {
  const match = /^aip\s+(\S+)\s+(language|format)\s+(\S+)/m.exec(String(text || ''));
  if (!match) return null;
  const [line, aip, kind, number] = match;
  return kind === 'language' ? { aip, language: number, line } : { aip, language: null, format: number, line };
}

/** `aip --version`, parsed: `{status: 'version', aip, language, line}`, or `not-found` / `failed`. */
async function version({ command = 'aip', timeoutMs } = {}) {
  const result = await run(command, ['--version'], { timeoutMs });
  if (result.status !== 'exited') return result;
  const parsed = parseVersion(result.stdout);
  if (!parsed) {
    return { status: 'failed', error: `unexpected output from aip --version: ${(result.stdout || result.stderr).trim() || `exit ${result.code}`}`,
      stdout: result.stdout, stderr: result.stderr, code: result.code };
  }
  return { status: 'version', ...parsed };
}

/** A diagnostic's span as a 0-based, end-exclusive range. An empty span (a syntax error at a
 * point) widens to one character so the editor has something to underline; the editor clamps
 * a range past the end of the document. */
function toRange(diagnostic) {
  const line = Math.max(0, (diagnostic.line || 1) - 1);
  const character = Math.max(0, (diagnostic.column || 1) - 1);
  let endLine = Math.max(line, (diagnostic.end_line || diagnostic.line || 1) - 1);
  let endCharacter = Math.max(0, (diagnostic.end_column || diagnostic.column || 1) - 1);
  if (endLine === line && endCharacter <= character) {
    endLine = line;
    endCharacter = character + 1;
  }
  return { start: { line, character }, end: { line: endLine, character: endCharacter } };
}

/** The report's diagnostics as plain objects the editor turns into its own: `{range, severity,
 * message, code, step}`, severity one of error, warning, info. */
function toDiagnostics(report) {
  return (report.diagnostics || []).map((d) => ({
    range: toRange(d),
    severity: SEVERITIES.includes(d.severity) ? d.severity : 'info',
    message: d.message,
    code: d.code,
    step: d.step === undefined ? null : d.step,
  }));
}

/** Call `fn` once, `ms` after the last call. `.cancel()` drops a pending call. */
function debounce(fn, ms) {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, ms);
  };
  wrapped.cancel = () => {
    clearTimeout(timer);
    timer = null;
  };
  return wrapped;
}

module.exports = { INSTALL_HINT, splitCommand, run, check, version, parseVersion, toRange, toDiagnostics, debounce };
