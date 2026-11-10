import { useEffect, useState } from "react";
import { api, describe } from "../api/client";
import { isFolderMode, localRun, localRuns } from "../api/console";
import type { StepGraph } from "../graph/model.ts";
import { emptyTraffic, fold, type Traffic } from "../graph/traffic.ts";

export type TrafficState =
  | { state: "loading"; done: number; total: number }
  | { state: "ready"; traffic: Traffic; ofName: number }
  | { state: "error"; message: string };

const LIMIT = 1000;        // the server's cap on one listing
const CONCURRENCY = 8;

/** Read every run of `name` (the newest LIMIT) and fold the ones that ran this bundle over its graph, while
 *  `enabled`. From the server; in folder mode, from this machine's run files of the folder. */
export function useTraffic(graph: StepGraph | null, name: string, bundleId: string | null, enabled: boolean): TrafficState | null {
  const [state, setState] = useState<TrafficState | null>(null);
  useEffect(() => {
    if (!enabled || !graph || !bundleId) return;
    const folder = isFolderMode();
    let cancelled = false;
    setState({ state: "loading", done: 0, total: 0 });
    (async () => {
      const all = await (folder ? localRuns() : api.runs({ name, limit: LIMIT }));
      if (cancelled) return;
      // A local listing does not say which bundle a run ran: its record does.
      const runs = folder ? all : all.filter((r) => r.bundle_id === bundleId);
      setState({ state: "loading", done: 0, total: runs.length });
      const traffic = emptyTraffic();
      let next = 0, done = 0;
      const worker = async () => {
        while (next < runs.length && !cancelled) {
          const summary = runs[next++];
          const record = await (folder ? localRun(summary.run_id) : api.run(summary.run_id));
          if (record.bundle_id === bundleId) fold(traffic, graph, record);
          done++;
          if (!cancelled) setState({ state: "loading", done, total: runs.length });
        }
      };
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, runs.length) }, worker));
      if (!cancelled) setState({ state: "ready", traffic, ofName: all.length });
    })().catch((e: unknown) => { if (!cancelled) setState({ state: "error", message: describe(e) }); });
    return () => { cancelled = true; };
  }, [graph, name, bundleId, enabled]);
  return enabled ? state : null;
}

/** The line above the graph: how many runs of this bundle, how they ended, and how many of the name's runs
 *  ran another revision and so are left out. */
export function TrafficSummary({ state }: { state: TrafficState }) {
  if (state.state === "loading") {
    return <p className="muted small" data-testid="traffic-loading">Reading {state.total ? `${state.done} of ${state.total} runs` : "the runs"}…</p>;
  }
  if (state.state === "error") return <p className="error" role="alert">{state.message}</p>;
  const t = state.traffic;
  const others = state.ofName - t.runs;
  const elsewhere = others ? ` ${others} ${others === 1 ? "run" : "runs"} of this name ran another revision and ${others === 1 ? "is" : "are"} not counted.` : "";
  if (t.runs === 0) {
    return (
      <p className="muted small" data-testid="traffic-summary" data-runs={0} data-of-name={state.ofName}>
        No runs of this revision yet; edges thicken with the runs that take them.{elsewhere}
      </p>
    );
  }
  const ended = Object.entries(t.byStatus).sort().map(([s, n]) => `${n} ${s}`).join(", ");
  return (
    <p className="muted small" data-testid="traffic-summary" data-runs={t.runs} data-of-name={state.ofName}>
      {state.ofName === LIMIT ? `${t.runs} of the newest ${LIMIT} runs of this name ran` : `${t.runs} ${t.runs === 1 ? "run" : "runs"} of`} this revision ({ended}).
      Edges thicken with the runs that took them; a step's badge is the runs that reached it, red when some failed there.{elsewhere}
    </p>
  );
}

/** Every step and loop with the runs that reached it, wait at it and failed there, busiest first. */
export function TrafficTable({ traffic, graph }: { traffic: Traffic; graph: StepGraph }) {
  const ids = Object.keys(graph.nodes).sort((a, b) => (graph.nodes[a].line ?? 0) - (graph.nodes[b].line ?? 0));
  const rows = ids.map((id) => ({ id, node: graph.nodes[id], runs: traffic.nodes.get(id) ?? 0, failed: traffic.failed.get(id) ?? 0, waiting: traffic.waiting.get(id) ?? 0 }))
    .sort((a, b) => b.runs - a.runs || ids.indexOf(a.id) - ids.indexOf(b.id));
  const total = traffic.runs || 1;
  return (
    <table className="compact" aria-label="run traffic">
      <thead><tr><th>step</th><th>runs reached</th><th>share</th><th>waiting here</th><th>failed here</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} data-testid="traffic-row" data-step={r.node.name} data-runs={r.runs} data-failed={r.failed} data-waiting={r.waiting}>
            <td><code>{r.node.name}</code> <span className="muted small">{r.node.kind}</span></td>
            <td className="num">{r.runs}</td>
            <td><span className="share-bar" aria-hidden="true"><span style={{ width: `${(100 * r.runs) / total}%` }} /></span> {Math.round((100 * r.runs) / total)}%</td>
            <td className="num">{r.waiting || <span className="muted">—</span>}</td>
            <td className="num">{r.failed ? <span className="run-error">{r.failed}</span> : <span className="muted">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
