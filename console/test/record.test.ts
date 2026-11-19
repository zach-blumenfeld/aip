// A run's history nested under its loops, on records as the server kept them (test/fixtures/*.run.json,
// from the scenes of the aip repo's tests/server/scenes.py): a loop that takes two passes, one that hits
// its cap, a For inside a Loop whose passes went to the model in one call, and a run with no loop.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import type { HistoryEntry, RunRecord } from "../src/api/types.ts";
import { duration, exitText, nest, timing, untilText, type LoopRows, type Row } from "../src/record/model.ts";

const record = (name: string) => JSON.parse(readFileSync(path.join(import.meta.dirname, "fixtures", `${name}.run.json`), "utf8")) as RunRecord;

/** A row as one word: a step's name, or a loop with its passes in brackets. */
function shape(row: Row): string {
  if (row.type === "step") return row.entry.step;
  return `${row.name}[${row.passes.map((p) => `${p.pass}:${p.rows.map(shape).join(" ")}`).join(" | ")}]`;
}

const loopOf = (rows: Row[], name: string) => rows.find((r): r is LoopRows => r.type === "loop" && r.name === name)!;

test("a run with no loop is its entries, in order", () => {
  const rows = nest(record("fired").history);
  assert.deepEqual(rows.map(shape), ["start", "triage", "by_tone", "escalate", "end"]);
  assert.deepEqual(rows.map((r) => (r.type === "step" ? r.seq : null)), [0, 1, 2, 3, 4]);
});

test("a loop's passes nest under it, with the test that let each run and the reason it ended", () => {
  const rows = nest(record("loop").history);
  assert.deepEqual(rows.map(shape), ["start", "draft", "revise[0:check summarize_check fix | 1:check summarize_check]", "end"]);
  const revise = loopOf(rows, "revise");
  assert.equal(revise.kind, "Loop");
  assert.equal(revise.exit?.reason, "until");
  assert.equal(revise.exit?.where, "summarize_check");
  assert.equal(revise.entry?.result.iterations, 2);

  // Pass 0 ran because the answer was not there yet; pass 1 because it was there and did not hold.
  assert.deepEqual(revise.passes[0].until, { holds: false, resolution: null, where: "head" });
  assert.equal(untilText(revise.passes[0].until!), "the Until answer was not in the state yet, so the pass ran");
  assert.equal(revise.passes[1].until?.resolution?.answer, "check_summary.all_hold");
  assert.equal(untilText(revise.passes[1].until!), "check_summary.all_hold was false: did not hold, so the pass ran");
  assert.equal(exitText(revise.exit!, 2), "its Until condition held at summarize_check, after 2 passes");
});

test("a loop at its cap says so", () => {
  const rows = nest(record("capped").history);
  assert.deepEqual(rows.map(shape), ["start", "draft", "revise[0:check summarize_check fix | 1:check summarize_check fix | 2:check summarize_check fix]"]);
  const revise = loopOf(rows, "revise");
  assert.equal(revise.exit?.reason, "cap");
  assert.equal(exitText(revise.exit!, 3), "it reached its cap after 3 passes without its condition holding");
});

test("a For inside a Loop: each outer pass has its own inner loop, closed by the For's own entry", () => {
  const rows = nest(record("batched").history);
  assert.deepEqual(rows.map(shape), [
    "start", "draft",
    "revise[0:review[0:check | 1:check | 2:check] summarize_check fix | 1:review[0:check | 1:check | 2:check] summarize_check]",
    "end",
  ]);
  const revise = loopOf(rows, "revise");
  const first = loopOf(revise.passes[0].rows, "review"), second = loopOf(revise.passes[1].rows, "review");
  assert.notEqual(first, second);
  assert.equal(first.kind, "For");
  assert.equal(first.exit?.reason, "items");
  assert.equal(exitText(first.exit!, 3), "every item was done, after 3 passes");
  // The Loop's head test for a pass is written on the first entry at its level, here the For's own.
  assert.equal(revise.passes[0].until?.resolution, null);
  assert.equal(revise.passes[1].until?.holds, false);
  assert.equal(first.passes[0].until, null);
});

test("a run still inside a loop, and a loop that ran no pass", () => {
  const history = record("loop").history;
  const waiting = nest(history.slice(0, 4));                    // start, draft, check, summarize_check: paused at fix
  assert.deepEqual(waiting.map(shape), ["start", "draft", "revise[0:check summarize_check]"]);
  assert.equal(loopOf(waiting, "revise").exit, null);
  assert.equal(loopOf(waiting, "revise").kind, null);

  const empty: HistoryEntry[] = [
    { step: "start", kind: "Start", pass: null, passes: [], at: "", input: {}, result: {} },
    { step: "revise", kind: "Loop", pass: null, passes: [], at: "", input: {}, result: { iterations: 0 }, exit: { reason: "until", where: "head" } },
    { step: "end", kind: "End", pass: null, passes: [], at: "", input: {}, result: {} },
  ];
  assert.deepEqual(nest(empty).map(shape), ["start", "revise[]", "end"]);
  assert.equal(exitText({ reason: "until", where: "head" }, 0), "its Until condition held at the head, after 0 passes");
});

test("where the time went: steps, the model (a batched call once), and waiting on agents", () => {
  const entry = (extra: Partial<HistoryEntry>): HistoryEntry => ({ step: "s", kind: "Decide", pass: null, passes: [], at: "", input: {}, result: {}, ...extra });
  const inPass = (outer: number, inner: number) => [{ loop: "revise", pass: outer }, { loop: "review", pass: inner }];
  const spent = timing([
    entry({ kind: "Task_Agent", seconds: 0.5, waited_seconds: 30 }),
    entry({ step: "check", seconds: 2, model_seconds: 2, batched: true, batch_size: 2, passes: inPass(0, 0) }),
    entry({ step: "check", seconds: 2, model_seconds: 2, batched: true, batch_size: 2, passes: inPass(0, 1) }),
    entry({ step: "check", seconds: 3, model_seconds: 3, batched: true, batch_size: 2, passes: inPass(1, 0) }),
    entry({ step: "triage", seconds: 1, model_seconds: 0.9 }),
  ]);
  assert.deepEqual(spent, { steps: 8.5, model: 5.9, waited: 30 });
  assert.equal(duration(0.0124), "12 ms");
  assert.equal(duration(1.44), "1.4 s");
  assert.equal(duration(125), "2 min 5 s");
  assert.equal(duration(undefined), "");
});
