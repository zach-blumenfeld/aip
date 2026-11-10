// Editing a procedure from its cards (plan C2): every operation is a text edit at a span of
// procedure.aip, found through the source spans `aip compile --json` puts on the graph. Nothing here
// changes the graph: the host applies the edits to the text, formats it, compiles it again, and draws
// what the compiler made of it, so the compiler is the only rule book and a card never says what the
// runtime would refuse. The edits are plain ranges, so the console applies them to a string and the
// VS Code preview can hand them to the document as they are.
//
// Spans are 1-based, `end_column` the column after the last character (the compiler's). The functions
// assume the canonical form `aip fmt` writes (one clause per line, a step's closing brace on its own
// line), which the Studio restores after every edit. No imports but the model, no DOM: it runs under
// node as it is (test/edit.test.ts).

import type { Graph, GraphEdge, GraphNode } from "./model.ts";

/** Replace `line:column` up to `endLine:endColumn` (exclusive) with `text`; an insertion when the two are equal. */
export interface TextEdit { line: number; column: number; endLine: number; endColumn: number; text: string }

/** The kinds a card may be added as: every step kind but the one `Start` and the one `End`. */
export const ADDABLE = ["Task_Agent", "Execute", "Decide", "Route", "Aggregate"] as const;
export type AddableKind = (typeof ADDABLE)[number];

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

/** The whole lines `first` to `last`, with the blank line after them when there is one: a block cut out. */
function cutLines(source: string, first: number, last: number): TextEdit {
  const all = lines(source);
  let end = last + 1;
  if ((all[end - 1] ?? "x").trim() === "" && end <= all.length && (all[first - 2] ?? "").trim() === "") end += 1;
  return { line: first, column: 1, endLine: end, endColumn: 1, text: "" };
}

const indentOf = (source: string, line: number) => /^\s*/.exec(lines(source)[line - 1] ?? "")![0];

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

/** Every step and loop name, `end` and `start` included: what a new step may not be called. */
function takenNames(graph: Graph): Set<string> {
  const taken = new Set(["end", "start", "index", "iterations", "continue"]);
  for (const n of graph.nodes) if (n.labels.includes("Step") || n.labels.includes("Loop") || n.labels.includes("Data")) taken.add(str(n.properties.name));
  return taken;
}

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

// ------------------------------------------------------------------ names

const STOP = new Set(["a", "an", "the", "of", "to", "and", "or", "for", "in", "on", "with", "is", "it", "its", "be", "by", "as", "at",
                      "this", "that", "from", "into", "if", "then", "so", "before", "after"]);

/** A step name from a description: its first three words that say something, lowercase, joined by `_`;
 *  `step` when there are none; a number added when the name is taken. */
export function nameFor(description: string, graph: Graph): string {
  const words = description.toLowerCase().replace(/[^a-z0-9\s]/g, " ").split(/\s+/).filter((w) => w && !STOP.has(w));
  let base = words.slice(0, 3).join("_") || "step";
  if (!/^[a-z]/.test(base)) base = `step_${base}`;
  const taken = takenNames(graph);
  if (!taken.has(base)) return base;
  for (let i = 2; ; i++) if (!taken.has(`${base}_${i}`)) return `${base}_${i}`;
}

// ------------------------------------------------------------------ the operations

export interface NewCard {
  kind: AddableKind;
  description: string;
  /** The card or loop the new one is written after (inside the same block). */
  after: string;
  /** Where it goes: a step or loop name, `end`, or `Continue` inside a loop body. */
  next: string;
  /** Execute: the script. */
  script?: string;
  /** Route: the answer it reads (`triage_decision.tone`) and its values; Aggregate: the answer it aggregates. */
  answer?: string;
  labels?: string[];
}

/** Add a card: a block of `kind` after `after`, in the shape spec 2.1 gives a card of that kind, named from its description. */
export function addCard(_source: string, graph: Graph, card: NewCard): { edits: TextEdit[]; name: string } {
  const at = itemSpan(graph, card.after);
  const name = nameFor(card.description, graph);
  const desc = literal(card.description.trim() || "What this step does.");
  const body: string[] = [];
  switch (card.kind) {
    case "Task_Agent":
      body.push(`Task_Agent ${name} ${desc} {`, `  Next_Step ${card.next}`, "}");
      break;
    case "Execute":
      body.push(`Execute ${name} ${desc} {`, `  Run_Script ${card.script || `scripts/${name}.py`}`, `  Next_Step ${card.next}`, "}");
      break;
    case "Decide":
      body.push(`Decide ${name} ${desc} {`, "  Answer_Questions {", `    answer: true_or_false ${desc}`, "  }", `  Produce ${name}`,
                `  Next_Step ${card.next}`, "}");
      break;
    case "Route":
      body.push(`Route ${name} ${desc} {`);
      if (card.answer) {
        body.push(`  Read ${card.answer}`);
        for (const label of card.labels ?? []) body.push(`  ${label} -> ${card.next}`);
      }
      body.push("}");
      break;
    case "Aggregate": {
      const source_ = card.answer ?? "";
      body.push(`Aggregate ${name} ${desc} {`);
      if (source_) body.push(`  Read ${source_.split(".")[0]}`);
      body.push("  Aggregations {", `    all_hold: All ${source_ || "answer"}`, "  }", `  Produce ${name}`, `  Next_Step ${card.next}`, "}");
      break;
    }
  }
  const indent = " ".repeat(at.column - 1);
  const text = "\n\n" + body.map((l) => indent + l).join("\n");
  return { edits: [{ line: at.endLine, column: at.endColumn, endLine: at.endLine, endColumn: at.endColumn, text }], name };
}

/** Remove a card or a loop: its whole block. */
export function removeItem(source: string, graph: Graph, id: string): TextEdit[] {
  const node = nodeOf(graph, id);
  const kind = str(node.properties.kind);
  if (kind === "Start" || kind === "End") throw new EditError(`a procedure has one ${kind}; it cannot be removed`);
  const at = itemSpan(graph, id);
  return [cutLines(source, at.line, at.endLine)];
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

/** Take a way out away: its line goes, and the compiler says what is missing until another is drawn. */
export function disconnect(_source: string, edge: GraphEdge): TextEdit[] {
  const at = edgeSpan(edge);
  return [{ line: at.line, column: 1, endLine: at.endLine + 1, endColumn: 1, text: "" }];
}

/** Insert a clause line just above a block's closing brace. */
function beforeClose(source: string, graph: Graph, id: string, clause: string): TextEdit {
  const at = itemSpan(graph, id);
  const indent = indentOf(source, at.line) + "  ";
  return { line: at.endLine, column: 1, endLine: at.endLine, endColumn: 1, text: `${indent}${clause}\n` };
}

/** Add a branch to a route: `label -> target`, or with `label` null its check, `Confidence_Below <bound> -> target`. */
export function addBranch(source: string, graph: Graph, route: string, label: string | null, target: string, bound = 0.8): TextEdit[] {
  return [beforeClose(source, graph, route, label === null ? `Confidence_Below ${bound} -> ${target}` : `${label} -> ${target}`)];
}

/** Give a card or a loop the way out it lacks: `Next_Step target` (or `Continue`) as its last line. */
export function addNext(source: string, graph: Graph, id: string, target: string): TextEdit[] {
  return [beforeClose(source, graph, id, target === "Continue" ? "Continue" : `Next_Step ${target}`)];
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

/** The `Read` items of a step, in written order (a key interpolated into a question is not one). */
function readsOf(graph: Graph, step: string): GraphEdge[] {
  return graph.edges.filter((e) => e.end === step && e.type === "READ_BY" && e.properties.interpolated !== true && spanOf(e.properties))
    .sort((a, b) => (num(a.properties.line)! - num(b.properties.line)!) || (num(a.properties.column)! - num(b.properties.column)!));
}

/** What a `READ_BY` edge reads, as written: `key` or `key.field`. */
export const readKey = (graph: Graph, e: GraphEdge) =>
  `${nameOf(graph, e.start)}${typeof e.properties.field === "string" && e.properties.field ? `.${e.properties.field}` : ""}`;

/** The line a step's clauses start on: the one after its header, which ends at the brace. */
function firstClauseLine(source: string, graph: Graph, step: string): number {
  const at = itemSpan(graph, step);
  const brace = source.indexOf("{", offsetOf(source, at.line, at.column));
  return position(source, brace).line + 1;
}

/** Add `key` to what a step reads. */
export function addRead(source: string, graph: Graph, step: string, key: string): TextEdit[] {
  const reads = readsOf(graph, step);
  if (reads.length) {
    const last = edgeSpan(reads[reads.length - 1]);
    return [{ line: last.endLine, column: last.endColumn, endLine: last.endLine, endColumn: last.endColumn, text: `, ${key}` }];
  }
  const line = firstClauseLine(source, graph, step);
  return [{ line, column: 1, endLine: line, endColumn: 1, text: `${indentOf(source, itemSpan(graph, step).line)}  Read ${key}\n` }];
}

/** Take `key` out of what a step reads; the `Read` line goes with the last one. */
export function removeRead(source: string, graph: Graph, step: string, key: string): TextEdit[] {
  const reads = readsOf(graph, step);
  const gone = reads.find((e) => readKey(graph, e) === key);
  if (!gone) throw new EditError(`${nameOf(graph, step)} does not read ${key}`);
  const first = edgeSpan(reads[0]), last = edgeSpan(reads[reads.length - 1]);
  if (reads.length === 1) return [{ line: first.line, column: 1, endLine: last.endLine + 1, endColumn: 1, text: "" }];
  const kept = reads.filter((e) => e !== gone).map((e) => textAt(source, edgeSpan(e)));
  return [{ line: first.line, column: first.column, endLine: last.endLine, endColumn: last.endColumn, text: kept.join(", ") }];
}

/** The keys a step produces, in written order (a `Start`'s are its inputs). */
function producesOf(graph: Graph, step: string): GraphEdge[] {
  return graph.edges.filter((e) => e.start === step && e.type === "PRODUCES" && spanOf(e.properties))
    .sort((a, b) => (num(a.properties.line)! - num(b.properties.line)!) || (num(a.properties.column)! - num(b.properties.column)!));
}

/** Add a key a step produces, `name: type "description"`; on `Start`, an input. Only `Execute`, `Task_Agent`
 *  and `Start` declare their keys one by one (a `Decide` or an `Aggregate` produces the one key of its questions). */
export function addOutput(source: string, graph: Graph, step: string, output: { name: string; type: string; description?: string }): TextEdit[] {
  const kind = str(nodeOf(graph, step).properties.kind);
  if (!["Execute", "Task_Agent", "Start"].includes(kind)) throw new EditError(`a ${kind} produces one key, named by its questions or aggregations`);
  const decl = `${output.name}: ${output.type}${output.description ? ` ${literal(output.description)}` : ""}`;
  const indent = indentOf(source, itemSpan(graph, step).line) + "  ";
  const produced = producesOf(graph, step);
  if (kind === "Start" || produced.length === 0) {
    const next = exitsOf(graph, step)[0];
    const line = next ? edgeSpan(next).line : itemSpan(graph, step).endLine;
    return [{ line, column: 1, endLine: line, endColumn: 1, text: `${indent}${kind === "Start" ? "" : "Produce "}${decl}\n` }];
  }
  const last = edgeSpan(produced[produced.length - 1]);
  return [{ line: last.endLine, column: last.endColumn, endLine: last.endLine, endColumn: last.endColumn,
            text: `\n${indent}        ${decl}` }];
}

/** Take a key out of what a step produces (an input out of `Start`); the `Produce` line goes with the last one. */
export function removeOutput(source: string, graph: Graph, step: string, key: string): TextEdit[] {
  const kind = str(nodeOf(graph, step).properties.kind);
  const produced = producesOf(graph, step);
  const gone = produced.find((e) => nameOf(graph, e.end) === key);
  if (!gone) throw new EditError(`${nameOf(graph, step)} does not produce ${key}`);
  if (!["Execute", "Task_Agent", "Start"].includes(kind)) throw new EditError(`a ${kind}'s key is its questions or aggregations`);
  const at = edgeSpan(gone);
  if (kind === "Start") return [{ line: at.line, column: 1, endLine: at.endLine + 1, endColumn: 1, text: "" }];
  const first = edgeSpan(produced[0]), last = edgeSpan(produced[produced.length - 1]);
  if (produced.length === 1) return [{ line: first.line, column: 1, endLine: last.endLine + 1, endColumn: 1, text: "" }];
  const indent = indentOf(source, itemSpan(graph, step).line) + "          ";
  const kept = produced.filter((e) => e !== gone).map((e) => textAt(source, edgeSpan(e)));
  return [{ line: first.line, column: first.column, endLine: last.endLine, endColumn: last.endColumn, text: kept.join(`\n${indent}`) }];
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

/** Move a card into a loop's body (written last in it, before the loop's exit line), or with `loop` null out of
 *  the loop it is in (written after that loop). The flows it had stay as written: the compiler says which no
 *  longer hold. */
export function move(source: string, graph: Graph, id: string, loop: string | null): TextEdit[] {
  const at = itemSpan(graph, id);
  const parent = graph.edges.find((e) => e.type === "CONTAINS" && e.end === id)?.start ?? null;
  if (loop === parent) throw new EditError(loop ? `${nameOf(graph, id)} is in ${nameOf(graph, loop)} already` : `${nameOf(graph, id)} is in no loop`);
  const all = lines(source);
  const block = all.slice(at.line - 1, at.endLine).join("\n");
  const cut = cutLines(source, at.line, at.endLine);
  let line: number;
  if (loop === null) {
    line = itemSpan(graph, parent!).endLine;
  } else {
    if (id === loop || isInside(graph, loop, id)) throw new EditError("a loop cannot go into itself");
    const children = graph.edges.filter((e) => e.type === "CONTAINS" && e.start === loop && e.end !== id)
      .sort((a, b) => (num(a.properties.order) ?? 0) - (num(b.properties.order) ?? 0));
    line = children.length ? itemSpan(graph, children[children.length - 1].end).endLine : itemSpan(graph, loop).line;
  }
  const end = (all[line - 1] ?? "").length + 1;
  return [cut, { line, column: end, endLine: line, endColumn: end, text: `\n\n${block}` }];
}

function isInside(graph: Graph, id: string, ancestor: string): boolean {
  let parent = graph.edges.find((e) => e.type === "CONTAINS" && e.end === id)?.start;
  for (let depth = 0; parent && depth < 64; depth++) {
    if (parent === ancestor) return true;
    parent = graph.edges.find((e) => e.type === "CONTAINS" && e.end === parent)?.start;
  }
  return false;
}

// ------------------------------------------------------------------ what a card can offer

/** One key, or one answer of a decision or an aggregation, that a step may read. */
export interface Offer {
  /** As a `Read` names it: `message`, `triage_decision.tone`. */
  key: string;
  type: string;
  /** An answer's values: a choice's or a score's labels, `true` and `false`. Empty for anything else. */
  labels: string[];
}

const ANSWER = new Set(["true_or_false", "choice", "score"]);
const BACK = new Set(["NEXT", "BRANCH", "BELOW", "CONTINUES", "ENTERS"]);

/** The keys produced upstream of `step` (by the steps and loops before it, or by Start), with the answers of
 *  the decisions and aggregations among them: what the canvas offers to read. The compiler still decides
 *  what is available on every path; this is the list to pick from. */
export function upstreamOf(graph: Graph, step: string, self = false): Offer[] {
  const seen = new Set<string>([step]);
  const queue = [step];
  // A step in a loop body is reached from its loop's own predecessors too.
  for (let id: string | undefined = step; id; ) {
    id = graph.edges.find((e) => e.type === "CONTAINS" && e.end === id)?.start;
    if (id && !seen.has(id)) { seen.add(id); queue.push(id); }
  }
  while (queue.length) {
    const id = queue.shift()!;
    for (const e of graph.edges) {
      if (e.end === id && BACK.has(e.type) && !seen.has(e.start)) { seen.add(e.start); queue.push(e.start); }
    }
  }
  // With `self`, what the step itself produces too: the offer for a card written after it.
  if (!self) seen.delete(step);
  // A loop upstream brings what its body produces (once it has run) and its own item and collected list.
  for (const id of [...seen]) {
    for (const e of graph.edges) if (e.type === "CONTAINS" && e.start === id) seen.add(e.end);
  }
  const offers: Offer[] = [];
  const add = (o: Offer) => { if (!offers.some((x) => x.key === o.key)) offers.push(o); };
  for (const e of graph.edges) {
    if (!seen.has(e.start) || !["PRODUCES", "BINDS", "COLLECTS"].includes(e.type)) continue;
    const data = graph.nodes.find((n) => n.id === e.end);
    if (!data) continue;
    const key = str(data.properties.name), type = str(data.properties.type);
    const labels = Array.isArray(data.properties.labels) ? (data.properties.labels as unknown[]).map(String) : type === "true_or_false" ? ["true", "false"] : [];
    add({ key, type, labels: ANSWER.has(type) ? labels : [] });
    // The fields of a decision or an aggregation are its answers.
    for (const f of graph.edges.filter((x) => x.start === e.start && (x.type === "ASKS" || x.type === "AGGREGATES"))) {
      const q = graph.nodes.find((n) => n.id === f.end);
      if (!q) continue;
      const qtype = f.type === "AGGREGATES" ? "true_or_false" : str(q.properties.type);
      const qlabels = Array.isArray(q.properties.labels) ? (q.properties.labels as unknown[]).map(String) : qtype === "true_or_false" ? ["true", "false"] : [];
      add({ key: `${key}.${str(q.properties.name)}`, type: qtype, labels: qlabels });
    }
  }
  return offers;
}

/** The values a route's answer can take that no branch names yet, and whether it has its check. */
export function unrouted(graph: Graph, route: string): { labels: string[]; checked: boolean } {
  const read = readsOf(graph, route)[0];
  const branched = new Set(graph.edges.filter((e) => e.start === route && e.type === "BRANCH").map((e) => str(e.properties.value)));
  const checked = graph.edges.some((e) => e.start === route && e.type === "BELOW");
  if (!read) return { labels: [], checked };
  const key = readKey(graph, read);
  const offer = upstreamOf(graph, route).find((o) => o.key === key);
  return { labels: (offer?.labels ?? []).filter((l) => !branched.has(l)), checked };
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
