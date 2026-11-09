import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RunSummary } from "../api/types";
import { describe } from "./Source";

/** How the recorded runs of one revision went through its graph: runs per edge and per step. Runs on other
 *  revisions of the name are left out, since their graph may differ: a step they share with this revision (start,
 *  end) would otherwise outweigh the steps they do not. */
export interface Traffic {
  /** Runs per `from->to` edge. */
  edges: Map<string, number>;
  /** Runs that entered each step (a step a run went through twice counts once). */
  steps: Map<string, number>;
  /** Runs that failed at each step. */
  failed: Map<string, number>;
  /** Runs on this revision (an edge or a step count is out of `runs`). */
  runs: number;
  /** Runs of the name on every revision, this one included. */
  ofName: number;
  byStatus: Record<string, number>;
}

export type TrafficState =
  | { state: "loading"; done: number; total: number }
  | { state: "ready"; traffic: Traffic }
  | { state: "error"; message: string };

const LIMIT = 1000;        // the server's cap on one listing
const CONCURRENCY = 8;

/** Fetch every run of `name` (newest LIMIT), fold the histories of those on `revision`, while `enabled`. */
export function useTraffic(name: string, revision: string, enabled: boolean): TrafficState | null {
  const [state, setState] = useState<TrafficState | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ state: "loading", done: 0, total: 0 });
    (async () => {
      const all = await api.runs({ name, limit: LIMIT });
      if (cancelled) return;
      const runs = all.filter((r) => r.revision === revision);
      setState({ state: "loading", done: 0, total: runs.length });
      const traffic = empty(runs, all.length);
      let next = 0, done = 0;
      const worker = async () => {
        while (next < runs.length && !cancelled) {
          const summary = runs[next++];
          const detail = await api.run(summary.run_id);
          // A paused run waits at a step it has not recorded yet (the entry is written once answered): count it.
          const waiting = detail.pause && detail.pause.kind !== "error" && detail.pause.step ? [{ step: detail.pause.step, kind: detail.pause.kind }] : [];
          fold(traffic, [...detail.history, ...waiting]);
          done++;
          if (!cancelled) setState({ state: "loading", done, total: runs.length });
        }
      };
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, runs.length) }, worker));
      if (!cancelled) setState({ state: "ready", traffic });
    })().catch((e: unknown) => { if (!cancelled) setState({ state: "error", message: describe(e) }); });
    return () => { cancelled = true; };
  }, [name, revision, enabled]);
  return enabled ? state : null;
}

function empty(runs: RunSummary[], ofName: number): Traffic {
  const byStatus: Record<string, number> = {};
  for (const r of runs) byStatus[r.status] = (byStatus[r.status] ?? 0) + 1;
  return { edges: new Map(), steps: new Map(), failed: new Map(), runs: runs.length, ofName, byStatus };
}

function fold(t: Traffic, history: { step: string; kind: string }[]) {
  const edges = new Set<string>();
  const steps = new Set<string>();
  let previous: string | null = null;
  for (const h of history) {
    if (!h.step) continue;
    steps.add(h.step);
    if (h.kind === "error") t.failed.set(h.step, (t.failed.get(h.step) ?? 0) + 1);
    if (previous !== null && previous !== h.step) edges.add(`${previous}->${h.step}`);
    previous = h.step;
  }
  for (const e of edges) t.edges.set(e, (t.edges.get(e) ?? 0) + 1);
  for (const s of steps) t.steps.set(s, (t.steps.get(s) ?? 0) + 1);
}

/** The line above the graph: how many runs of this revision, how they ended, and how many of the name's runs
 *  are on other revisions and so left out. */
export function TrafficSummary({ state }: { state: TrafficState }) {
  if (state.state === "loading") {
    return <p className="muted small" data-testid="traffic-loading">Reading {state.total ? `${state.done} of ${state.total} runs` : "the runs"}…</p>;
  }
  if (state.state === "error") return <p className="error" role="alert">{state.message}</p>;
  const t = state.traffic;
  const others = t.ofName - t.runs;
  const elsewhere = others ? ` ${others} ${others === 1 ? "run" : "runs"} of this name on other revisions ${others === 1 ? "is" : "are"} not counted.` : "";
  if (t.runs === 0) {
    return (
      <p className="muted small" data-testid="traffic-summary" data-runs={0} data-of-name={t.ofName}>
        No runs of this revision yet; edges thicken with the runs that take them.{elsewhere}
      </p>
    );
  }
  const ended = Object.entries(t.byStatus).sort().map(([s, n]) => `${n} ${s}`).join(", ");
  return (
    <p className="muted small" data-testid="traffic-summary" data-runs={t.runs} data-of-name={t.ofName}>
      {t.ofName === LIMIT ? `${t.runs} of the newest ${LIMIT} runs of this name are` : `${t.runs} ${t.runs === 1 ? "run" : "runs"}`} on this revision ({ended}).
      Edges thicken with the runs that took them; a step's badge is the runs that reached it, red when some failed there.{elsewhere}
    </p>
  );
}

/** Every step with the runs that reached it and failed there, busiest first. */
export function TrafficTable({ traffic, steps }: { traffic: Traffic; steps: string[] }) {
  const rows = steps.map((s) => ({ step: s, runs: traffic.steps.get(s) ?? 0, failed: traffic.failed.get(s) ?? 0 }))
    .sort((a, b) => b.runs - a.runs || steps.indexOf(a.step) - steps.indexOf(b.step));
  const total = traffic.runs || 1;
  return (
    <table className="compact" aria-label="run traffic">
      <thead><tr><th>step</th><th>runs reached</th><th>share</th><th>failed here</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.step} data-testid="traffic-row" data-step={r.step} data-runs={r.runs} data-failed={r.failed}>
            <td><a href={`#step-${r.step}`}><code>{r.step}</code></a></td>
            <td className="num">{r.runs}</td>
            <td><span className="share-bar" aria-hidden="true"><span style={{ width: `${(100 * r.runs) / total}%` }} /></span> {Math.round((100 * r.runs) / total)}%</td>
            <td className="num">{r.failed ? <span className="run-error">{r.failed}</span> : <span className="muted">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
