import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CatalogEntry, HistoryEntry, ProcedureInfo, RunDetail, RunStatus, RunSummary } from "../api/types";
import { href, navigate } from "../router";
import { RunStepCard } from "./RunStepCard";
import { describe } from "./Source";
import { DirectionToggle, StepGraph, useDirection } from "./StepGraph";

const STATUSES: RunStatus[] = ["running", "paused", "done", "failed"];

/** View 4a: the runs the server persisted, filtered by name and status (`GET /runs`). */
export function Runs({ name, status }: { name?: string; status?: string }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.catalog().then((all: CatalogEntry[]) => setNames(all.map((c) => c.name))).catch(() => setNames([]));
  }, []);

  useEffect(() => {
    setRuns(null);
    setError(null);
    api.runs({ name, status, limit: 200 }).then(setRuns).catch((e: unknown) => setError(describe(e)));
  }, [name, status]);

  const filter = (next: { name?: string; status?: string }) =>
    navigate({ page: "runs", name: next.name || undefined, status: next.status || undefined });

  return (
    <article className="history">
      <h1>History</h1>
      <p className="muted">Runs this server persisted, newest first. Open one to replay it over the step graph.</p>
      <div className="filters">
        <label>name{" "}
          <select aria-label="name" value={name ?? ""} onChange={(e) => filter({ name: e.target.value, status })}>
            <option value="">any</option>
            {names.map((n) => <option key={n} value={n}>{n}</option>)}
            {name && !names.includes(name) && <option value={name}>{name}</option>}
          </select>
        </label>
        <label>status{" "}
          <select aria-label="status" value={status ?? ""} onChange={(e) => filter({ name, status: e.target.value })}>
            <option value="">any</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {!error && runs === null && <p className="muted">Loading runs…</p>}
      {runs && runs.length === 0 && <p className="muted" data-testid="no-runs">No runs match.</p>}
      {runs && runs.length > 0 && (
        <table aria-label="runs">
          <thead><tr><th>run</th><th>procedure</th><th>status</th><th>steps</th><th>started</th><th>updated</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} data-testid="run-row" data-run-id={r.run_id} data-status={r.status}>
                <td><a href={href({ page: "run-detail", id: r.run_id })}><code>{r.run_id}</code></a></td>
                <td><a href={href({ page: "procedure", ref: `${r.name}@${r.revision}` })}>{r.name}</a><span className="muted"> @{r.revision}</span></td>
                <td><span className={`status-tag run-${r.status}`}>{r.status}</span></td>
                <td className="num">{r.steps}</td>
                <td className="when">{when(r.started_at)}</td>
                <td className="when">{when(r.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** View 4b: one run from `GET /runs/{id}`, its history as a trace over the graph and read-only step cards. */
export function RunPage({ id }: { id: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [info, setInfo] = useState<ProcedureInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useDirection();

  useEffect(() => {
    setRun(null);
    setInfo(null);
    setError(null);
    api.run(id)
      .then(async (r) => { setRun(r); setInfo(await api.info(`${r.name}@${r.revision}`)); })
      .catch((e: unknown) => setError(describe(e)));
  }, [id]);

  // A paused run waits at a step it has not recorded yet (a step's entry is written once it is answered): the
  // trace ends there.
  const trace = useMemo(() => {
    const waiting = run?.pause && run.pause.kind !== "error" ? [{ step: run.pause.step } as HistoryEntry] : [];
    return traceOf([...(run?.history ?? []), ...waiting]);
  }, [run]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!run || !info) return <p className="muted">Loading run {id}…</p>;

  const ref = `${info.name}@${info.revision}`;
  const pause = run.status === "paused" || run.status === "failed" ? run.pause : null;

  return (
    <article className="run history-run">
      <nav className="crumbs">
        <a href={href({ page: "runs" })}>history</a> / <a href={href({ page: "runs", name: info.name })}><code>{info.name}</code></a> / <code>{run.run_id}</code>
      </nav>
      <h1>{info.name} <span className="muted rev">run @{info.revision}</span></h1>
      <p className="run-meta">
        <span>status <strong data-testid="run-status" className={`run-${run.status}`}>{run.status}</strong></span>
        <span> · started {when(run.started_at)}</span>
        <span> · updated {when(run.updated_at)}</span>
        <span> · {run.history.length} {run.history.length === 1 ? "entry" : "entries"}</span>
        {" · "}<a href={href({ page: "procedure", ref })}>procedure</a>
        {" · "}<a href={href({ page: "run", ref })}>new run</a>
      </p>

      <div className="run-grid">
        <div>
          {run.history.length === 0 && <p className="muted">This run has no history yet.</p>}
          {run.history.map((entry, i) => (
            <RunStepCard key={i} entry={entry} info={info} index={i + 1} />
          ))}
          {pause && (
            <section className="pause" data-testid="run-pause">
              <h2>{pause.kind === "error" ? "Failed at" : "Paused at"} <code>{pause.step}</code></h2>
              {pause.kind === "client_task" && (
                <>
                  <p className="muted">
                    Waiting for the client to do this task and produce{" "}
                    {Object.keys(pause.answer_with).map((k, i) => <span key={k}>{i ? ", " : ""}<code>{k}</code></span>)}.
                  </p>
                  <pre className="task" data-testid="task">{pause.task}</pre>
                </>
              )}
              {pause.kind === "decision" && <p className="muted">Waiting for the client to answer the decision's questions.</p>}
              {pause.kind === "execute" && <p className="muted">Waiting for the client to run <code>{pause.script}</code> and report.</p>}
              {pause.kind === "error" && <p className="muted"><code>{pause.error}</code>: the run kept the state before this step; <code>aip resume {run.run_id}</code> retries it.</p>}
              <p className="muted small">Runs are resumed from the client that started them (the run console, or <code>aip resume</code>); this page only replays.</p>
            </section>
          )}
          {run.status === "done" && (
            <section className="pause" data-testid="run-done">
              <h2>Done</h2>
              <p className="muted">The final state is the end step's card above.</p>
            </section>
          )}
        </div>

        <aside className={direction === "right" ? "wide" : undefined}>
          <h2>Trace</h2>
          <div className="graph-controls">
            <p className="muted small">Visited steps and the edges taken are highlighted.</p>
            <DirectionToggle direction={direction} onChange={setDirection} />
          </div>
          <StepGraph steps={info.step_details} edges={info.edges} branches={info.branches}
                     start={info.start.step} end={info.end.step} visited={trace.visited} taken={trace.taken} direction={direction} />
          <ol className="trace small" data-testid="trace">
            {run.history.map((h, i) => <li key={i}><code>{h.step}</code> <span className="muted">{h.kind}</span></li>)}
          </ol>
        </aside>
      </div>
    </article>
  );
}

/** The steps a history visited and the edges it walked, in order, as `from->to`. */
export function traceOf(history: HistoryEntry[]): { visited: Set<string>; taken: Set<string> } {
  const visited = new Set<string>();
  const taken = new Set<string>();
  let previous: string | null = null;
  for (const h of history) {
    if (!h.step) continue;
    visited.add(h.step);
    if (previous !== null && previous !== h.step) taken.add(`${previous}->${h.step}`);
    previous = h.step;
  }
  return { visited, taken };
}
