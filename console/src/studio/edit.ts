// The Studio's field edits (plan C4; through C2 every card operation was here): each is a text edit at a
// span of procedure.aip, found through the source spans `aip compile --json` puts on the graph. A form
// edits what a person changes by hand: a description or a question, a confidence bar, a loop's cap, its
// `Until` and what it does at the cap, an answer's labels, where a step goes next among the steps there
// are. Anything structural (a new step, a loop, a rewire) is asked of the chat, which runs
// edit_procedure. Nothing here changes the graph: the page applies the edits to the text, the launcher
// formats and compiles it, and the graph is drawn again from what the compiler made of it, so the
// compiler is the only rule book.
//
// Spans are 1-based, `end_column` the column after the last character (the compiler's). The functions
// assume the canonical form `aip fmt` writes (one clause per line, a step's closing brace on its own
// line), which the Studio restores after every edit. No imports but the bundle's types, no DOM: it runs
// under node as it is (test/edit.test.ts).

import type { Graph, GraphEdge, GraphNode } from "../graph/bundle.ts";

/** Replace `line:column` up to `endLine:endColumn` (exclusive) with `text`; an insertion when the two are equal. */
export interface TextEdit { line: number; column: number; endLine: number; endColumn: number; text: string }

export class EditError extends Error {}

// ------------------------------------------------------------------ applying

/** The text with `edits` applied. The edits are all against `source` as it is, and must not overlap. */
export function applyEdits(source: string, edits: TextEdit[]): string {
  const starts = [0];
  for (let i = 0; i < source.length; i++) if (source[i] === "\n") starts.push(i + 1);
  const offset = (line: number, column: number) => {
    if (line > starts.length) return source.length;
    return Math.min((starts[line - 1] ?? source.length) + column - 1, source.length);
  };
  const ranges = edits.map((e) => ({ from: offset(e.line, e.column), to: offset(e.endLine, e.endColumn), text: e.text }))
    .sort((a, b) => b.from - a.from || b.to - a.to);
  let out = source;
  for (const r of ranges) out = out.slice(0, r.from) + r.text + out.slice(r.to);
  return out;
}

// ------------------------------------------------------------------ reading the graph

interface Span { line: number; column: number; endLine: number; endColumn: number }

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");

function spanOf(props: Record<string, unknown>): Span | null {
  const line = num(props.line), column = num(props.column), endLine = num(props.end_line), endColumn = num(props.end_column);
  return line !== null && column !== null && endLine !== null && endColumn !== null ? { line, column, endLine, endColumn } : null;
}

const lines = (source: string) => source.split("\n");

function textAt(source: string, s: Span): string {
  const all = lines(source);
  if (s.line === s.endLine) return (all[s.line - 1] ?? "").slice(s.column - 1, s.endColumn - 1);
  const parts = [(all[s.line - 1] ?? "").slice(s.column - 1)];
  for (let l = s.line + 1; l < s.endLine; l++) parts.push(all[l - 1] ?? "");
  parts.push((all[s.endLine - 1] ?? "").slice(0, s.endColumn - 1));
  return parts.join("\n");
}

function nodeOf(graph: Graph, id: string): GraphNode {
  const node = graph.nodes.find((n) => n.id === id);
  if (!node) throw new EditError(`no ${id} in the graph`);
  return node;
}

function itemSpan(graph: Graph, id: string): Span {
  const span = spanOf(nodeOf(graph, id).properties);
  if (!span) throw new EditError(`the graph has no source span for ${id}; compile it with aip compile --json`);
  return span;
}

function edgeSpan(edge: GraphEdge): Span {
  const span = spanOf(edge.properties);
  if (!span) throw new EditError(`the graph has no source span for that ${edge.type} line`);
  return span;
}

const nameOf = (graph: Graph, id: string) => str(graph.nodes.find((n) => n.id === id)?.properties.name) || id.replace(/^[a-z]+:/, "");

/** A way out of a card or a loop: the edges a port is drawn from. */
export const FLOW = new Set(["NEXT", "BRANCH", "BELOW", "CONTINUES"]);

/** The flow edges out of `id`, in written order. */
export function exitsOf(graph: Graph, id: string): GraphEdge[] {
  return graph.edges.filter((e) => e.start === id && FLOW.has(e.type))
    .sort((a, b) => (num(a.properties.line) ?? 0) - (num(b.properties.line) ?? 0));
}

// ------------------------------------------------------------------ strings

/** `text` as a string literal of the language: a double-quoted string, `\"` and `\\` escaped. */
export function literal(text: string): string {
  return `"${text.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** Where the first string literal at or after `from` is, scanning no further than `until`. */
function findLiteral(text: string, from: number, until: number): { from: number; to: number } | null {
  for (let i = from; i < until; i++) {
    if (text[i] === "#") { while (i < until && text[i] !== "\n") i++; continue; }
    if (text[i] !== '"') continue;
    if (text.startsWith('"""', i)) {
      const end = text.indexOf('"""', i + 3);
      return end < 0 ? null : { from: i, to: end + 3 };
    }
    for (let j = i + 1; j < text.length; j++) {
      if (text[j] === "\\") { j++; continue; }
      if (text[j] === '"') return { from: i, to: j + 1 };
    }
    return null;
  }
  return null;
}

function position(source: string, offset: number): { line: number; column: number } {
  const before = source.slice(0, offset).split("\n");
  return { line: before.length, column: before[before.length - 1].length + 1 };
}

function offsetOf(source: string, line: number, column: number): number {
  const all = lines(source);
  let o = 0;
  for (let l = 1; l < line; l++) o += (all[l - 1] ?? "").length + 1;
  return o + column - 1;
}

function replaceRange(source: string, from: number, to: number, text: string): TextEdit {
  const a = position(source, from), b = position(source, to);
  return { line: a.line, column: a.column, endLine: b.line, endColumn: b.column, text };
}

/** Replace the string a named string `name = "..."` holds. */
function setNamedString(source: string, name: string, text: string): TextEdit {
  const m = new RegExp(`^[ \\t]*${name}[ \\t]*=[ \\t]*`, "m").exec(source);
  if (!m) throw new EditError(`no named string ${name} to change`);
  const at = findLiteral(source, m.index + m[0].length, source.length);
  if (!at) throw new EditError(`${name} holds no string`);
  return replaceRange(source, at.from, at.to, literal(text));
}

/** Replace the string that ends a header (`Kind name "..." {`) or a span, or the named string it uses. */
function setStringIn(source: string, from: number, until: number, text: string): TextEdit {
  const at = findLiteral(source, from, until);
  if (at) return replaceRange(source, at.from, at.to, literal(text));
  const words = source.slice(from, until).replace(/#.*$/gm, "").match(/[a-z][a-z0-9_]*/g) ?? [];
  const name = words[words.length - 1];
  if (!name) throw new EditError("found no description to change");
  return setNamedString(source, name, text);
}

/** Point a way out (a `Next_Step`, a branch, a check, a `Continue`) at `target`: a step or loop name, `end`, or `Continue`. */
export function connect(source: string, edge: GraphEdge, target: string): TextEdit[] {
  const at = edgeSpan(edge);
  const text = textAt(source, at);
  const whole = /^\s*(Continue|Next_Pass)\s*$/i.test(text);
  if (whole || (edge.type === "NEXT" && target === "Continue")) {
    // A line that is only `Continue`, or a `Next_Step` becoming one: the whole clause changes.
    return [{ ...at, endLine: at.endLine, text: target === "Continue" ? "Continue" : `Next_Step ${target}` }];
  }
  const m = /(\S+)\s*$/.exec(text);
  if (!m) throw new EditError("that line names no target");
  const startOffset = offsetOf(source, at.line, at.column) + m.index;
  return [replaceRange(source, startOffset, startOffset + m[1].length, target)];
}

/** Change a bound: a route's `Confidence_Below` (its `BELOW` edge), or a loop's `At_Most`. */
export function setBound(source: string, graph: Graph, owner: string, value: number): TextEdit[] {
  const below = graph.edges.find((e) => e.start === owner && e.type === "BELOW");
  if (below) {
    const at = edgeSpan(below);
    const text = textAt(source, at);
    const m = /(Confidence_Below\s+)([0-9.]+)/i.exec(text);
    if (!m) throw new EditError("the check names no bound");
    const from = offsetOf(source, at.line, at.column) + m.index + m[1].length;
    return [replaceRange(source, from, from + m[2].length, String(value))];
  }
  const node = nodeOf(graph, owner);
  if (!node.labels.includes("Loop")) throw new EditError(`${nameOf(graph, owner)} has no bound to change`);
  const at = itemSpan(graph, owner);
  const from = offsetOf(source, at.line, at.column);
  const brace = source.indexOf("{", from);
  const header = source.slice(from, brace);
  const m = /((?:At_Most|Max)\s+)(\d+)/i.exec(header) ?? /(\s)(\d+)(?=\s+Times)/i.exec(header);
  if (!m) throw new EditError(`${nameOf(graph, owner)} has no cap written`);
  const start = from + m.index + m[1].length;
  return [replaceRange(source, start, start + m[2].length, String(Math.max(1, Math.round(value))))];
}

/** Change a description: a step's, the procedure's (`procedure`), or a question's instruction (`question:<step>.<name>`).
 *  When it is written as a named string, the named string changes. */
export function setText(source: string, graph: Graph, id: string, text: string): TextEdit[] {
  const at = itemSpan(graph, id);
  const from = offsetOf(source, at.line, at.column);
  const node = nodeOf(graph, id);
  if (node.labels.includes("Question")) return [setStringIn(source, from, offsetOf(source, at.endLine, at.endColumn), text)];
  if (node.labels.includes("Procedure")) {
    // The description follows `Procedure <name>`, possibly on the next line; nothing else in the header is a bare word.
    const m = /Procedure\s+[a-z][a-z0-9_]*\s+/i.exec(source.slice(from));
    if (!m) throw new EditError("found no Procedure line");
    const start = from + m.index + m[0].length;
    if (source[start] === '"') return [setStringIn(source, start, start + 1, text)];
    const word = /^[a-z][a-z0-9_]*/.exec(source.slice(start));
    if (!word) throw new EditError("found no description after the Procedure line");
    return [setNamedString(source, word[0], text)];
  }
  if (node.labels.includes("Loop")) throw new EditError("a loop has no description");
  return [setStringIn(source, from, source.indexOf("{", from), text)];
}

/** Rename the procedure: the name on its `Procedure` line, which is the name it is published under. */
export function renameProcedure(source: string, graph: Graph, name: string): TextEdit[] {
  if (!/^[a-z][a-z0-9_]*$/.test(name)) throw new EditError(`${JSON.stringify(name)} is not a name: lowercase letters, digits and _, a letter first`);
  const at = itemSpan(graph, "procedure");
  const from = offsetOf(source, at.line, at.column);
  const m = /^Procedure(\s+)([a-z][a-z0-9_]*)/i.exec(source.slice(from));
  if (!m) throw new EditError("found no Procedure line");
  const start = from + "Procedure".length + m[1].length;
  return [replaceRange(source, start, start + m[2].length, name)];
}

/** Where a way out may lead from `id`: every step and loop of the same block, `end` outside a loop body,
 *  `Continue` inside one. Flows across a loop's braces are the compiler's to refuse; these are the ones it allows. */
export function targetsFor(graph: Graph, id: string): string[] {
  const parentOf = (x: string) => graph.edges.find((e) => e.type === "CONTAINS" && e.end === x)?.start ?? null;
  const parent = parentOf(id);
  const names = graph.nodes
    .filter((n) => (n.labels.includes("Step") || n.labels.includes("Loop")) && n.id !== id && parentOf(n.id) === parent)
    .filter((n) => str(n.properties.kind) !== "Start" && str(n.properties.kind) !== "End")
    .map((n) => str(n.properties.name));
  return parent === null ? [...names, "end"] : [...names, "Continue"];
}

/** The header of a loop, from its keyword to the brace: where `Until`, `At_Most` and `Else_*` are written. */
function loopHeader(source: string, graph: Graph, loop: string): { from: number; text: string } {
  const node = nodeOf(graph, loop);
  if (!node.labels.includes("Loop")) throw new EditError(`${nameOf(graph, loop)} is not a loop`);
  const at = itemSpan(graph, loop);
  const from = offsetOf(source, at.line, at.column);
  return { from, text: source.slice(from, source.indexOf("{", from)) };
}

/** Change what a `Loop ... Until` watches: the condition between `Until` and the next clause, written as given
 *  (`passed`, `review.verdict == approved With Confidence_Above 0.8`). The compiler says whether it is one. */
export function setUntil(source: string, graph: Graph, loop: string, condition: string): TextEdit[] {
  const clean = condition.replace(/\s+/g, " ").trim();
  if (!clean || /[,{}]/.test(clean)) throw new EditError("a condition is one answer, optionally `== value` and `With Confidence_Above p`, with no comma or brace");
  const header = loopHeader(source, graph, loop);
  const m = /(Until\s+)([^,]*?)(\s*(?:,|$))/i.exec(header.text);
  if (!m) throw new EditError(`${nameOf(graph, loop)} has no Until: a loop of a fixed count runs its passes`);
  const start = header.from + m.index + m[1].length;
  return [replaceRange(source, start, start + m[2].length, clean)];
}

/** What an `Until` loop does when its cap is reached without the condition: `Else_Fail` fails the run, `Else_Exit`
 *  leaves by the exit line. */
export function setAtCap(source: string, graph: Graph, loop: string, atCap: "Else_Fail" | "Else_Exit"): TextEdit[] {
  const header = loopHeader(source, graph, loop);
  if (!/Until\s/i.test(header.text)) throw new EditError(`${nameOf(graph, loop)} has no Until, so reaching its count is its end`);
  const m = /Else_(?:Fail|Exit)/i.exec(header.text);
  if (m) return [replaceRange(source, header.from + m.index, header.from + m.index + m[0].length, atCap)];
  const cap = /(At_Most|Max)\s+\d+/i.exec(header.text);
  if (!cap) throw new EditError(`${nameOf(graph, loop)} has no cap written`);
  const end = header.from + cap.index + cap[0].length;
  return [replaceRange(source, end, end, `, ${atCap}`)];
}

/** The answer a node declares labels for: a question of a `Decide` (`question:<step>.<name>`), or a key a step
 *  produces with an answer type (`data:<name>`). The routes that branch on it read `key.field`, or `key`. */
function answerOf(graph: Graph, owner: string): { span: Span; key: string; field: string | null; labels: string[] } {
  const node = nodeOf(graph, owner);
  const labels = Array.isArray(node.properties.labels) ? (node.properties.labels as unknown[]).map(String) : [];
  if (node.labels.includes("Question")) {
    const step = graph.edges.find((e) => e.type === "ASKS" && e.end === owner)?.start;
    const data = step ? graph.edges.find((e) => e.type === "PRODUCES" && e.start === step)?.end : undefined;
    if (!data) throw new EditError(`found no key for ${nameOf(graph, owner)}`);
    return { span: itemSpan(graph, owner), key: data, field: str(node.properties.name), labels };
  }
  if (node.labels.includes("Data")) {
    const produced = graph.edges.find((e) => e.type === "PRODUCES" && e.end === owner && spanOf(e.properties));
    if (!produced) throw new EditError(`found nowhere ${nameOf(graph, owner)} is declared`);
    return { span: edgeSpan(produced), key: owner, field: null, labels };
  }
  throw new EditError(`${nameOf(graph, owner)} has no labels`);
}

/** Change an answer's labels (a `choice` or a `score`): the list in brackets where it is declared. A label
 *  renamed (the same place in the list, a new word) is renamed too where a route branches on it and on a
 *  criterion line under a question; a label added or taken away is the compiler's to report on the routes
 *  that read the answer. */
export function setLabels(source: string, graph: Graph, owner: string, labels: string[]): TextEdit[] {
  const clean = labels.map((l) => l.trim()).filter(Boolean);
  for (const l of clean) {
    if (!/^[a-z][a-z0-9_]*$/.test(l)) throw new EditError(`${JSON.stringify(l)} is not a label: lowercase letters, digits and _, a letter first`);
  }
  if (clean.length < 2) throw new EditError("an answer has at least two labels");
  if (new Set(clean).size !== clean.length) throw new EditError("a label is written twice");
  const answer = answerOf(graph, owner);
  const from = offsetOf(source, answer.span.line, answer.span.column);
  const to = offsetOf(source, answer.span.endLine, answer.span.endColumn);
  const open = source.indexOf("[", from), close = source.indexOf("]", open);
  if (open < 0 || open > to || close < 0) throw new EditError(`${nameOf(graph, owner)} declares no labels in brackets`);
  const edits = [replaceRange(source, open + 1, close, clean.join(", "))];

  const renamed = new Map<string, string>();
  answer.labels.forEach((old, i) => {
    const now = clean[i];
    if (now !== undefined && now !== old && !answer.labels.includes(now)) renamed.set(old, now);
  });
  if (renamed.size === 0) return edits;
  // The branches of the routes that read this answer: `old -> target` becomes `new -> target`.
  const routes = new Set(graph.edges.filter((e) => e.type === "READ_BY" && e.start === answer.key &&
    (answer.field === null ? !e.properties.field : e.properties.field === answer.field)).map((e) => e.end));
  for (const e of graph.edges) {
    if (e.type !== "BRANCH" || !routes.has(e.start)) continue;
    const now = renamed.get(str(e.properties.value));
    if (!now) continue;
    const at = edgeSpan(e);
    const start = offsetOf(source, at.line, at.column);
    const word = /^\s*([a-z][a-z0-9_]*)/.exec(source.slice(start));
    if (word) edits.push(replaceRange(source, start + word[0].length - word[1].length, start + word[0].length, now));
  }
  // A question's criteria: the lines under it, deeper in, that open with a label and a colon.
  if (answer.field !== null) {
    const all = lines(source);
    const indent = /^\s*/.exec(all[answer.span.line - 1] ?? "")![0].length;
    for (let l = answer.span.endLine + 1; l <= all.length; l++) {
      const m = /^(\s*)([a-z][a-z0-9_]*)(\s*:\s*)/.exec(all[l - 1]);
      if (!m || m[1].length <= indent) break;
      const now = renamed.get(m[2]);
      if (now) edits.push({ line: l, column: m[1].length + 1, endLine: l, endColumn: m[1].length + 1 + m[2].length, text: now });
    }
  }
  return edits;
}
