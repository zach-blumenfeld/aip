// A run's path over the step graph, and the traffic of many runs. The history is flat (aip
// docs/cli-json.md, The run file): one entry per step that finished, each naming the loop passes it
// ran inside, and one per loop when it exits. An entry does not say which arrow it left by, so the
// graph does: a route's entry names where it went (`to`), every other step has one way out, and a
// loop's own entry leaves by the loop's exit line (and says when its `Until` ended it in the middle
// of the body). Passes of a `For` run side by side, so two
// entries next to each other in the history are not an arrow; this never pairs them up.
// No DOM: it runs under node as it is (test/graph.test.ts).

import type { HistoryEntry, PassRef, RunRecord } from "../api/types.ts";
import { edgeKey, inside, type StepGraph } from "./model.ts";

/** What of a run the path reads. */
export type RunLike = Pick<RunRecord, "history" | "status" | "position" | "pause" | "error">;

export interface RunPath {
  /** The ids of the steps and loops the run reached, the one it waits or stopped at included. */
  visited: Set<string>;
  /** How many times the run went along each arrow (`from->to`): a loop's passes repeat the arrows of its body. */
  taken: Map<string, number>;
  /** Where a paused run waits. */
  waiting: string | null;
  /** Where a failed run stopped. */
  failed: string | null;
}

const isLoop = (entry: HistoryEntry) => entry.kind === "For" || entry.kind === "Loop";
const idOf = (entry: HistoryEntry) => `${isLoop(entry) ? "loop" : "step"}:${entry.step}`;

export function pathOf(graph: StepGraph, run: RunLike): RunPath {
  const visited = new Set<string>();
  const taken = new Map<string, number>();
  const go = (from: string, to: string | undefined) => {
    if (to === undefined || !graph.edges.some((e) => e.from === from && e.to === to)) return;
    const key = edgeKey(from, to);
    taken.set(key, (taken.get(key) ?? 0) + 1);
  };
  const outOf = (id: string) => graph.edges.filter((e) => e.from === id && !e.enter);

  // Each pass of a loop enters its body once.
  const entered = new Set<string>();
  const enter = (passes: PassRef[] | undefined) => {
    (passes ?? []).forEach((ref, i) => {
      const loop = `loop:${ref.loop}`;
      visited.add(loop);
      const pass = (passes ?? []).slice(0, i + 1).map((p) => `${p.loop}#${p.pass}`).join("/");
      if (entered.has(pass)) return;
      entered.add(pass);
      go(loop, graph.nodes[loop]?.children[0]);
    });
  };

  for (const entry of run.history) {
    const id = idOf(entry);
    visited.add(id);
    enter(entry.passes);
    const ways = outOf(id);
    if (isLoop(entry)) {
      // A loop that fails at its cap goes nowhere; any other exit leaves by the loop's exit line.
      const failsAtCap = entry.exit?.reason === "cap" && (graph.nodes[id]?.title ?? "").includes("Else_Fail");
      if (!failsAtCap) go(id, ways[0]?.to);
      // An `Until` that held where its answer was produced ended the loop there: that step of the
      // body, the last time it ran, did not go on to the next.
      const where = entry.exit?.where ? `step:${entry.exit.where}` : null;
      if (where !== null && where in graph.nodes && inside(graph.nodes, where, id)) {
        const onward = outOf(where);
        const key = onward.length === 1 ? onward[0].key : null;
        const times = key === null ? 0 : taken.get(key) ?? 0;
        if (key !== null && times > 1) taken.set(key, times - 1);
        else if (key !== null) taken.delete(key);
      }
    } else if (entry.kind === "Route") {
      const target = entry.to === "Continue"
        ? ways.find((e) => e.toFrame)
        : ways.find((e) => !e.toFrame && graph.nodes[e.to]?.name === entry.to) ?? ways.find((e) => graph.nodes[e.to]?.name === entry.to);
      go(id, target?.to);
    } else if (ways.length === 1) {
      go(id, ways[0].to);
    }
  }

  const named = run.pause?.step ? `step:${run.pause.step}` : run.error?.loop ? `loop:${run.error.loop}` : run.error?.step ? `step:${run.error.step}` : null;
  // A run paused inside a `For` has its cursor on the loop (its passes wait side by side): the pause names the step.
  const here = run.status === "done" ? null : named ?? run.position;
  const at = here !== null && here in graph.nodes ? here : null;
  if (at !== null) {
    visited.add(at);
    for (const task of run.pause?.tasks ?? []) enter(task.passes);
    // The loops around where it stands were reached too.
    for (const id of Object.keys(graph.nodes)) if (graph.nodes[id].frame && inside(graph.nodes, at, id)) visited.add(id);
  }
  return { visited, taken, waiting: run.status === "paused" ? at : null, failed: run.status === "failed" ? at : null };
}

/** How the recorded runs of one bundle went through its graph. Runs of the name's other revisions are
 *  left out, since their graph may differ. */
export interface Traffic {
  /** Runs per arrow (`from->to`): a run that took an arrow in three passes counts once. */
  edges: Map<string, number>;
  /** Runs that reached each step or loop. */
  nodes: Map<string, number>;
  /** Runs that failed at each step or loop. */
  failed: Map<string, number>;
  /** Runs that wait at each step. */
  waiting: Map<string, number>;
  /** Runs of this bundle: every count is out of this. */
  runs: number;
  byStatus: Record<string, number>;
}

export function emptyTraffic(): Traffic {
  return { edges: new Map(), nodes: new Map(), failed: new Map(), waiting: new Map(), runs: 0, byStatus: {} };
}

/** Count one run into `traffic`. */
export function fold(traffic: Traffic, graph: StepGraph, run: RunLike): void {
  const bump = (map: Map<string, number>, key: string) => map.set(key, (map.get(key) ?? 0) + 1);
  const path = pathOf(graph, run);
  traffic.runs += 1;
  traffic.byStatus[run.status] = (traffic.byStatus[run.status] ?? 0) + 1;
  for (const key of path.taken.keys()) bump(traffic.edges, key);
  for (const id of path.visited) bump(traffic.nodes, id);
  if (path.failed) bump(traffic.failed, path.failed);
  if (path.waiting) bump(traffic.waiting, path.waiting);
}
