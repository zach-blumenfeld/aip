import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, describe, type AuditFilter } from "../api/client";
import type { AuditQuery, AuditRow, CatalogEntry } from "../api/types";
import { href, navigate } from "../router";

const DEFAULT_WINDOW = 100;
const DEFAULT_LIMIT = 50;

/** The audit queries of `GET /audit`, each answered by `GET /audit/{query}` and shown as a list
 *  (aip docs/server-design.md, Audit). The filters are the queries' parameters. */
export function Audit({ name }: { name?: string }) {
  const [queries, setQueries] = useState<AuditQuery[] | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [window, setWindow] = useState(DEFAULT_WINDOW);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [agent, setAgent] = useState("");
  const [session, setSession] = useState("");
  const [user, setUser] = useState("");
  const [draft, setDraft] = useState("");
  const [key, setKey] = useState("");

  const reload = useCallback(() => {
    api.audit().then(setQueries).catch((e: unknown) => setError(describe(e)));
  }, []);

  useEffect(() => {
    reload();
    api.catalog().then((all: CatalogEntry[]) => setNames(all.map((c) => c.name))).catch(() => setNames([]));
  }, [reload]);

  const filter: AuditFilter = {
    name, window, limit, agent: agent.trim() || undefined, session: session.trim() || undefined, user: user.trim() || undefined,
    draft: draft === "" ? undefined : draft === "true", key: key.trim() || undefined,
  };

  return (
    <article className="governance audit">
      <h1>Audit</h1>
      <p className="muted">
        What the record and the catalog say. Every run is local to the client that made it, which posts where it stopped: what
        each decision's model answered and how sure it was, which checks fired, who answered each task, how each loop ended.
        The first queries read the most recent runs that match the filters; the rest read the revision each published name
        resolves to. Pin and retire are on each procedure's page.
      </p>
      <div className="filters" data-testid="audit-filters">
        <label>procedure{" "}
          <select aria-label="procedure" value={name ?? ""} onChange={(e) => navigate({ page: "audit", name: e.target.value || undefined })}>
            <option value="">any</option>
            {names.map((n) => <option key={n} value={n}>{n}</option>)}
            {name && !names.includes(name) && <option value={name}>{name}</option>}
          </select>
        </label>
        <label>agent <input type="text" className="filter-field" aria-label="agent" value={agent} placeholder="any" onChange={(e) => setAgent(e.target.value)} /></label>
        <label>session <input type="text" className="filter-field" aria-label="session" value={session} placeholder="any" onChange={(e) => setSession(e.target.value)} /></label>
        <label>user <input type="text" className="filter-field" aria-label="user" value={user} placeholder="any" onChange={(e) => setUser(e.target.value)} /></label>
        <label>bundle{" "}
          <select aria-label="draft" value={draft} onChange={(e) => setDraft(e.target.value)}>
            <option value="">drafts and published</option>
            <option value="false">published only</option>
            <option value="true">drafts only</option>
          </select>
        </label>
        <label>last{" "}
          <input className="num-field" type="number" min={1} max={100000} aria-label="window" value={window}
                 onChange={(e) => setWindow(Math.max(1, Number(e.target.value) || DEFAULT_WINDOW))} /> runs
        </label>
        <label>up to{" "}
          <input className="num-field" type="number" min={1} max={10000} aria-label="limit" value={limit}
                 onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || DEFAULT_LIMIT))} /> rows
        </label>
        <label>key <input type="text" className="filter-field" aria-label="key" value={key} placeholder="for lineage" onChange={(e) => setKey(e.target.value)} /></label>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {!error && queries === null && <p className="muted">Loading the queries…</p>}
      {queries?.map((q) => <QueryList key={q.query} query={q} filter={filter} onRemoved={reload} />)}
      {queries !== null && <AddQuery onStored={reload} />}
    </article>
  );
}

type Saving = { kind: "idle" } | { kind: "busy" } | { kind: "error"; message: string };

/** Keep a query of your own: it runs on the server in a transaction that is never committed, with the same
 *  parameters the built-ins get, and appears in the list above. Needs the publish scope. */
function AddQuery({ onStored }: { onStored: () => void }) {
  const [query, setQuery] = useState("");
  const [description, setDescription] = useState("");
  const [cypher, setCypher] = useState("");
  const [saving, setSaving] = useState<Saving>({ kind: "idle" });
  const ready = /^[a-z0-9]+(-[a-z0-9]+)*$/.test(query) && cypher.trim().length > 0 && saving.kind !== "busy";

  const store = () => {
    setSaving({ kind: "busy" });
    api.storeAuditQuery(query, { description, cypher })
      .then(() => { setSaving({ kind: "idle" }); setQuery(""); setDescription(""); setCypher(""); onStored(); })
      .catch((e: unknown) => setSaving({ kind: "error", message: describe(e) }));
  };

  return (
    <section className="query add-query" data-testid="add-query" data-state={saving.kind}>
      <h2>Add a query</h2>
      <p className="muted">
        Cypher over the store (the graph is in aip's <code>docs/language/queries.md</code>), kept on the server and run read-only
        whenever this page asks. It may use <code>$name</code>, <code>$agent</code>, <code>$session</code>, <code>$user</code>,
        <code> $draft</code>, <code>$window</code>, <code>$limit</code>, <code>$repeats</code>, <code>$key</code> and <code>$bundles</code> (the
        ids of the resolved revisions), like the built-in queries.
      </p>
      <label className="field">
        <span>name <span className="muted small">lowercase, digits and hyphens</span></span>
        <input type="text" value={query} aria-label="query name" data-testid="query-name" disabled={saving.kind === "busy"}
               onChange={(e) => setQuery(e.target.value.trim())} />
      </label>
      <label className="field">
        <span>description</span>
        <input type="text" value={description} aria-label="query description" data-testid="query-description"
               disabled={saving.kind === "busy"} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="field">
        <span>cypher</span>
        <textarea className="json" rows={Math.min(16, Math.max(4, cypher.split("\n").length + 1))} value={cypher}
                  aria-label="cypher" data-testid="query-cypher" disabled={saving.kind === "busy"}
                  onChange={(e) => { setCypher(e.target.value); if (saving.kind !== "busy") setSaving({ kind: "idle" }); }} />
      </label>
      <div className="actions">
        <button type="button" disabled={!ready} data-testid="store-query" onClick={store}>Keep this query</button>
      </div>
      {saving.kind === "error" && <p className="error small" role="alert">{saving.message}</p>}
    </section>
  );
}

type Answer =
  | { kind: "loading" }
  | { kind: "needs"; names: string[] }
  | { kind: "rows"; rows: AuditRow[] }
  | { kind: "error"; message: string };

function QueryList({ query, filter, onRemoved }: { query: AuditQuery; filter: AuditFilter; onRemoved: () => void }) {
  const [answer, setAnswer] = useState<Answer>({ kind: "loading" });
  const [removing, setRemoving] = useState<string | null>(null);   // an error message, or null
  // One string, so the effect runs when a parameter changes and not on every render.
  const asked = JSON.stringify(filter);

  const remove = () => {
    setRemoving(null);
    api.removeAuditQuery(query.query).then(onRemoved).catch((e: unknown) => setRemoving(describe(e)));
  };

  useEffect(() => {
    let live = true;
    const params = JSON.parse(asked) as AuditFilter;
    const missing = (query.needs ?? []).filter((n) => (params as Record<string, unknown>)[n] === undefined);
    if (missing.length > 0) { setAnswer({ kind: "needs", names: missing }); return; }
    setAnswer({ kind: "loading" });
    // Typing in a filter asks once it has settled.
    const timer = setTimeout(() => {
      api.auditQuery(query.query, params)
        .then((rows) => { if (live) setAnswer({ kind: "rows", rows }); })
        .catch((e: unknown) => { if (live) setAnswer({ kind: "error", message: describe(e) }); });
    }, 250);
    return () => { live = false; clearTimeout(timer); };
  }, [query.query, query.needs, asked]);

  return (
    <section className="query" data-testid="audit-query" data-query={query.query} data-state={answer.kind}
             data-builtin={query.builtin ? "true" : "false"}>
      <h2><code>{query.query}</code>{!query.builtin && <> <span className="status-tag" data-testid="stored-tag">stored</span></>}</h2>
      {query.description && <p className="muted">{query.description}</p>}
      {!query.builtin && (
        <div className="actions">
          <button type="button" data-testid="remove-query" onClick={remove}>Remove this query</button>
          {removing && <span className="error small" role="alert">{removing}</span>}
        </div>
      )}
      {answer.kind === "loading" && <p className="muted">Asking…</p>}
      {answer.kind === "needs" && <p className="muted" data-testid="needs">Give {answer.names.map((n) => <code key={n}>{n} </code>)} in the filters above to ask this one.</p>}
      {answer.kind === "error" && <p className="error" role="alert">{answer.message}</p>}
      {answer.kind === "rows" && answer.rows.length === 0 && <p className="muted" data-testid="no-rows">Nothing to report.</p>}
      {answer.kind === "rows" && answer.rows.length > 0 && <Rows rows={answer.rows} />}
    </section>
  );
}

/** Rows are flat; the columns are the keys in order of first appearance. */
function Rows({ rows }: { rows: AuditRow[] }) {
  const columns: string[] = [];
  for (const row of rows) for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key);
  return (
    <table className="compact" aria-label="rows">
      <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} data-testid="audit-row" data-name={cell(row.name)} data-step={cell(row.step)} data-route={cell(row.route)}
              data-reason={cell(row.reason)} data-question={cell(row.question)} data-loop={cell(row.loop)}>
            {columns.map((c) => <td key={c} className={typeof row[c] === "number" ? "num" : undefined}>{render(c, row[c])}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function cell(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

const NAMES_OF_THINGS = new Set(["step", "route", "question", "script", "loop", "aggregation", "key", "source", "produced_by", "branch"]);

function render(column: string, value: unknown): ReactNode {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  if (column === "reason" && typeof value === "string") {
    const why = value === "below" ? "the confidence was below the bound" : value === "absent" ? "the answer carried no confidence" : "";
    return <span className="status-tag check-fired" data-testid="reason" title={why}>{value}</span>;
  }
  if (column === "run_ids" && Array.isArray(value)) {
    const ids = value.filter((v): v is string => typeof v === "string");
    const shown = ids.slice(0, 5);
    return (
      <span data-testid="run-ids">
        {shown.map((id, i) => <span key={id}>{i ? ", " : ""}<a href={href({ page: "run-detail", id })}><code>{id}</code></a></span>)}
        {ids.length > shown.length && <span className="muted"> and {ids.length - shown.length} more</span>}
      </span>
    );
  }
  if (column === "name" && typeof value === "string") return <a href={href({ page: "procedure", ref: value })}><code>{value}</code></a>;
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "boolean") return String(value);
  if (typeof value === "string") return NAMES_OF_THINGS.has(column) ? <code>{value}</code> : value;
  if (Array.isArray(value)) return value.map((v, i) => <span key={i}>{i ? ", " : ""}<code>{typeof v === "string" ? v : JSON.stringify(v)}</code></span>);
  return <code>{JSON.stringify(value)}</code>;
}
