// A run's history as a reader wants it: the entries of a loop nested under the loop, pass by pass, with
// the test that let each pass run and the reason the loop ended. The history itself is flat (aip
// docs/cli-json.md, The run file): every entry names the passes it ran inside (`passes`, outermost
// first), and a loop writes one entry of its own, after its passes, when it exits. No imports and no
// DOM: it runs under node as it is (test/record.test.ts).

import type { HistoryEntry, LoopExit, PassRef, UntilTest } from "../api/types.ts";

/** One step's entry, with its place in the history (`seq`, from 0) and its time. */
export interface StepRow { type: "step"; seq: number; entry: HistoryEntry }

/** One pass of a loop: what ran in it, in order. `until` is the test at the head that let it run. */
export interface PassRows { pass: number; until: UntilTest | null; rows: Row[] }

/** A loop: its passes, and how it ended (`exit` null while the run is still inside it). */
export interface LoopRows {
  type: "loop";
  name: string;
  /** `For` or `Loop`, known once the loop has exited (its own entry says). */
  kind: "For" | "Loop" | null;
  passes: PassRows[];
  exit: LoopExit | null;
  /** The loop's own entry: `result.iterations`, a `For`'s collected list. */
  entry: HistoryEntry | null;
  seq: number | null;
}

export type Row = StepRow | LoopRows;

const isLoopEntry = (e: HistoryEntry) => e.kind === "For" || e.kind === "Loop";

/** The open loop called `name` among `rows`: the last one that has not exited. */
function openLoop(rows: Row[], name: string): LoopRows | null {
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    if (row.type === "loop" && row.name === name) return row.exit === null ? row : null;
  }
  return null;
}

/** The rows of the pass `path` names, made on the way down when the history has not shown it yet. */
function descend(root: Row[], path: PassRef[]): { rows: Row[]; pass: PassRows | null } {
  let rows = root;
  let found: PassRows | null = null;
  for (const ref of path) {
    let loop = openLoop(rows, ref.loop);
    if (!loop) {
      loop = { type: "loop", name: ref.loop, kind: null, passes: [], exit: null, entry: null, seq: null };
      rows.push(loop);
    }
    let pass = loop.passes.find((p) => p.pass === ref.pass);
    if (!pass) {
      pass = { pass: ref.pass, until: null, rows: [] };
      loop.passes.push(pass);
      loop.passes.sort((a, b) => a.pass - b.pass);
    }
    found = pass;
    rows = pass.rows;
  }
  return { rows, pass: found };
}

/** The history as nested rows. */
export function nest(history: HistoryEntry[]): Row[] {
  const root: Row[] = [];
  history.forEach((entry, seq) => {
    const { rows, pass } = descend(root, entry.passes ?? []);
    // The head's test is written on the first entry of the pass at the loop's own level.
    if (entry.until && pass && pass.until === null) pass.until = entry.until;
    if (!isLoopEntry(entry)) {
      rows.push({ type: "step", seq, entry });
      return;
    }
    let loop = openLoop(rows, entry.step);
    if (!loop) {
      // A loop that ran no pass (an empty list, an `Until` that held at the head).
      loop = { type: "loop", name: entry.step, kind: null, passes: [], exit: null, entry: null, seq: null };
      rows.push(loop);
    }
    loop.kind = entry.kind as "For" | "Loop";
    loop.exit = entry.exit ?? { reason: "items" };
    loop.entry = entry;
    loop.seq = seq;
  });
  return root;
}

/** Seconds as a reader's duration: `12 ms`, `1.4 s`, `2 min 5 s`. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}

/** Why a loop ended, in words. */
export function exitText(exit: LoopExit, passes: number): string {
  const count = `${passes} ${passes === 1 ? "pass" : "passes"}`;
  const where = exit.where && exit.where !== "head" ? ` at ${exit.where}` : exit.where === "head" ? " at the head" : "";
  switch (exit.reason) {
    case "until": return `its Until condition held${where}, after ${count}`;
    case "items": return `every item was done, after ${count}`;
    case "times": return `it ran its ${count}`;
    case "cap": return `it reached its cap after ${count} without its condition holding`;
    default: return `${exit.reason}, after ${count}`;
  }
}

/** The head's test of a pass, in words: why the pass ran. */
export function untilText(until: UntilTest): string {
  if (until.resolution === null || until.resolution === undefined) return "the Until answer was not in the state yet, so the pass ran";
  const r = until.resolution;
  const answer = r.answer ?? r.source ?? "the answer";
  if (r.barred) return `${answer} was barred (probability ${r.probability ?? "none"}), so the pass ran`;
  return `${answer} was ${JSON.stringify(r.value)}: ${until.holds ? "held" : "did not hold, so the pass ran"}`;
}

/** How long the run spent, by where the time went: its steps' own time, the model's, and waiting on agents. */
export function timing(history: HistoryEntry[]): { steps: number; model: number; waited: number } {
  let steps = 0, model = 0, waited = 0;
  const calls = new Set<string>();
  for (const e of history) {
    steps += e.seconds ?? 0;
    waited += e.waited_seconds ?? 0;
    if (e.model_seconds !== undefined) {
      // A batched call's time is on every pass it answered: count the call once.
      const outer = (e.passes ?? []).slice(0, -1).map((p) => `${p.loop}:${p.pass}`).join("/");
      const key = e.batched ? `${e.step}|${outer}` : "";
      if (!e.batched || !calls.has(key)) model += e.model_seconds;
      if (e.batched) calls.add(key);
    }
  }
  return { steps, model, waited };
}
