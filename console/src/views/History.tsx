import { useEffect, useMemo, useState } from "react";
import { api, describe } from "../api/client";
import { folderGraph, isFolderMode, localRun, localRuns } from "../api/console";
import type { CatalogEntry, RunRecord, RunStatus, RunSummary } from "../api/types";
import { Canvas } from "../canvas/Canvas.tsx";
import type { Graph } from "../canvas/model.ts";
import { Code } from "../highlight/Code.tsx";
import { bundleRef, href, navigate, type Route } from "../router";
import { DraftBadge, ErrorSummary, Json, PauseSummary, RecordHistory, RecordSummary, when } from "./Record";
import { DirectionToggle, useDirection } from "./StepGraph";
import { RunPath } from "./Steps";

const STATUSES: RunStatus[] = ["paused", "done", "failed"];

type RunsRoute = Extract<Route, { page: "runs" }>;

/** The runs the server holds, newest first (`GET /runs`), filtered by procedure, status, who ran them and whether
 *  they ran a draft. In folder mode, this machine's runs of the folder, unfiltered. */
export function Runs({ route }: { route: RunsRoute }) {
  const folder = isFolderMode();
  const { name, status, agent, session, user, draft } = route;
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (folder) return;
    api.catalog().then((all: CatalogEntry[]) => setNames(all.map((c) => c.name))).catch(() => setNames([]));
  }, [folder]);

  useEffect(() => {
    setRuns(null);
    setError(null);
    const asked = folder ? localRuns() : api.runs({ name, status, agent, session, user, draft, limit: 200 });
    asked.then(setRuns).catch((e: unknown) => setError(describe(e)));
  }, [folder, name, status, agent, session, user, draft]);

  const filter = (next: Partial<RunsRoute>) => {
    const merged = { ...route, ...next };
    navigate({ page: "runs", name: merged.name || undefined, status: merged.status || undefined, agent: merged.agent || undefined,
               session: merged.session || undefined, user: merged.user || undefined, draft: merged.draft });
  };

  return (
    <article className="history">
      <h1>History</h1>
      {folder
        ? <p className="muted">Runs of this folder on this machine, newest first. They are not recorded on a server.</p>
        : <p className="muted">Runs this server holds, newest first. Every run says which agent made it, in which session, and for which user.</p>}
      {!folder && (
        <div className="filters" data-testid="run-filters">
          <label>procedure{" "}
            <select aria-label="procedure" value={name ?? ""} onChange={(e) => filter({ name: e.target.value })}>
              <option value="">any</option>
              {names.map((n) => <option key={n} value={n}>{n}</option>)}
              {name && !names.includes(name) && <option value={name}>{name}</option>}
            </select>
          </label>
          <label>status{" "}
            <select aria-label="status" value={status ?? ""} onChange={(e) => filter({ status: e.target.value })}>
              <option value="">any</option>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <TextFilter label="agent" value={agent} onChange={(v) => filter({ agent: v })} />
          <TextFilter label="session" value={session} onChange={(v) => filter({ session: v })} />
          <TextFilter label="user" value={user} onChange={(v) => filter({ user: v })} />
          <label>bundle{" "}
            <select aria-label="draft" value={draft === undefined ? "" : String(draft)}
                    onChange={(e) => filter({ draft: e.target.value === "" ? undefined : e.target.value === "true" })}>
              <option value="">drafts and published</option>
              <option value="false">published only</option>
              <option value="true">drafts only</option>
            </select>
          </label>
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      {!error && runs === null && <p className="muted">Loading runs…</p>}
      {runs && runs.length === 0 && <p className="muted" data-testid="no-runs">No runs match.</p>}
      {runs && runs.length > 0 && (
        <table aria-label="runs">
          <thead><tr><th>run</th><th>procedure</th><th>status</th><th>agent</th><th>session</th><th>user</th><th>started</th><th>updated</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} data-testid="run-row" data-run-id={r.run_id} data-status={r.status} data-draft={String(r.draft)}
                  data-agent={r.identity?.agent ?? ""} data-session={r.identity?.session ?? ""}>
                <td><a href={href({ page: "run-detail", id: r.run_id })}><code>{r.run_id}</code></a></td>
                <td>
                  {folder ? r.name : <a href={href({ page: "procedure", ref: procedureRef(r) })}>{r.name}</a>}
                  {r.revision && <span className="muted"> @{r.revision}</span>} <DraftBadge draft={r.draft} />
                </td>
                <td><span className={`status-tag run-${r.status}`}>{r.status}</span></td>
                <td>{r.identity?.agent
                  ? (folder ? <code>{r.identity.agent}</code> : <button type="button" className="linkish" onClick={() => filter({ agent: r.identity.agent ?? undefined })}><code>{r.identity.agent}</code></button>)
                  : <span className="muted">—</span>}</td>
                <td>{r.identity?.session
                  ? (folder ? <code>{r.identity.session}</code> : <button type="button" className="linkish" onClick={() => filter({ session: r.identity.session ?? undefined })}><code>{r.identity.session}</code></button>)
                  : <span className="muted">—</span>}</td>
                <td>{r.identity?.user ? <code>{r.identity.user}</code> : <span className="muted">—</span>}</td>
                <td className="when">{when(r.started)}</td>
                <td className="when">{when(r.updated)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}

/** The page of the procedure a run ran: its revision, or the bundle itself when it has none. */
function procedureRef(run: { name: string; revision: string | null; bundle_id?: string }): string {
  if (run.revision) return `${run.name}@${run.revision}`;
  return run.bundle_id ? bundleRef(run.bundle_id) : run.name;
}

/** A filter typed in: applied when the field is left or Enter is pressed, so each key does not ask the server. */
function TextFilter({ label, value, onChange }: { label: string; value?: string; onChange: (v: string) => void }) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => { setText(value ?? ""); }, [value]);
  const apply = () => { if (text !== (value ?? "")) onChange(text.trim()); };
  return (
    <label>{label}{" "}
      <input type="text" className="filter-field" aria-label={label} value={text} placeholder="any" onChange={(e) => setText(e.target.value)}
             onBlur={apply} onKeyDown={(e) => { if (e.key === "Enter") apply(); }} />
    </label>
  );
}

/** One run: its record from the server (`GET /runs/{id}`), or in folder mode from this machine's run file. */
export function RunPage({ id }: { id: string }) {
  const folder = isFolderMode();
  const [run, setRun] = useState<RunRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useDirection();

  useEffect(() => {
    setRun(null);
    setError(null);
    (folder ? localRun(id) : api.run(id)).then(setRun).catch((e: unknown) => setError(describe(e)));
  }, [id, folder]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!run) return <p className="muted">Loading run {id}…</p>;
  const ref = procedureRef(run);

  return (
    <article className="run history-run">
      <nav className="crumbs">
        <a href={href({ page: "runs" })}>history</a>
        {!folder && <> / <a href={href({ page: "runs", name: run.name })}><code>{run.name}</code></a></>} / <code>{run.run_id}</code>
      </nav>
      <h1>{run.name} <span className="muted rev">run{run.revision ? ` @${run.revision}` : ""}</span> <DraftBadge draft={run.draft} /></h1>
      <p className="run-meta">
        <span>status <strong data-testid="run-status" className={`run-${run.status}`}>{run.status}</strong></span>
        <span> · {run.history.length} {run.history.length === 1 ? "entry" : "entries"}</span>
        {!folder && <>{" · "}<a href={href({ page: "procedure", ref })}>procedure</a></>}
        {!folder && run.revision && <>{" · "}<a href={href({ page: "run", ref })}>new run</a></>}
      </p>
      <RecordSummary record={run} />
      {/* Drawn to the right the graph is wide: it takes the whole row and the record moves below (as does a graph
          too wide for the column drawn down: styles.css). */}
      <div className={`path-grid${direction === "right" ? " wide" : ""}`}>
        <section className="run-path">
          <h2>Path</h2>
          <div className="graph-controls">
            <span className="muted small">Heavy: the steps this run reached and the arrows it took; ×n: an arrow a loop repeated.</span>
            <DirectionToggle direction={direction} onChange={setDirection} />
          </div>
          <RunPath record={run} direction={direction} />
        </section>
        <div className="run-record">
          <RunRecordBody record={run} />
        </div>
      </div>
      <RunCanvas record={run} />
    </article>
  );
}

/** The history, then where the run stands: the pause it waits at, the error it stopped on, or its result. */
export function RunRecordBody({ record }: { record: RunRecord }) {
  return (
    <>
      <RecordHistory record={record} />
      {record.status === "paused" && <PauseSummary record={record} />}
      {record.status === "failed" && record.error && <ErrorSummary error={record.error} runId={record.run_id} />}
      {record.status === "done" && (
        <section className="pause" data-testid="run-done">
          <h2>Done</h2>
          <p className="muted">The result: what the <code>End</code> step reads.</p>
          <Json value={record.result ?? {}} testid="run-result" />
        </section>
      )}
    </>
  );
}

/** The procedure the run ran, with the steps and loops it went through marked. */
function RunCanvas({ record }: { record: RunRecord }) {
  const [shown, setShown] = useState(false);
  const [graph, setGraph] = useState<{ graph: Graph; source: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const visited = useMemo(() => new Set(record.history.map((e) => e.step)), [record]);

  useEffect(() => {
    if (!shown || graph) return;
    const sourceIn = (g: Graph) => {
      const source = g.nodes.find((n) => n.labels.includes("Procedure"))?.properties.source;
      return typeof source === "string" ? source : "";
    };
    const asked = isFolderMode()
      ? folderGraph().then((f) => (f.graph ? { graph: f.graph, source: f.source } : Promise.reject(new Error("the folder does not compile now"))))
      : api.bundleGraph(record.bundle_id).then((b) => ({ graph: b.graph, source: sourceIn(b.graph) }));
    asked.then(setGraph).catch((e: unknown) => setError(describe(e)));
  }, [shown, graph, record.bundle_id]);

  return (
    <details className="run-canvas" onToggle={(e) => setShown((e.target as HTMLDetailsElement).open)}>
      <summary data-testid="show-run-canvas">the procedure as cards, with what this run went through marked</summary>
      {error && <p className="error" role="alert">{error}</p>}
      {shown && !graph && !error && <p className="muted">Loading the procedure…</p>}
      {shown && graph && (
        <Canvas graph={graph.graph} source={graph.source} visited={visited}
                renderCode={(code, first) => <Code text={code} aip firstLine={first} />} />
      )}
    </details>
  );
}
