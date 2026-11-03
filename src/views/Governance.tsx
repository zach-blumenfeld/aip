import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CatalogEntry, GovernanceQuery, GovernanceRow } from "../api/types";
import { href, navigate } from "../router";
import { describe } from "./Source";

const DEFAULT_WINDOW = 100;
const DEFAULT_LIMIT = 50;

/** View 5b: the corpus queries of `GET /governance`, each answered by `GET /governance/{query}` and shown as a list. */
export function Governance({ name }: { name?: string }) {
  const [queries, setQueries] = useState<GovernanceQuery[] | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [window, setWindow] = useState(DEFAULT_WINDOW);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);

  const reload = useCallback(() => {
    api.governance().then(setQueries).catch((e: unknown) => setError(describe(e)));
  }, []);

  useEffect(() => {
    reload();
    api.catalog().then((all: CatalogEntry[]) => setNames(all.map((c) => c.name))).catch(() => setNames([]));
  }, [reload]);

  return (
    <article className="governance">
      <h1>Governance</h1>
      <p className="muted">
        What the corpus says about the procedures and their runs. Decisions, scripts and tasks run on the clients, and
        each client reports who answered, how sure its model was and how a script ended, so these lists cover every
        machine that ran a procedure. Routers are walked by the server, which records when a confidence check fired.
        Pin and retire live on each procedure's page; a router's check, a decision's <code>fallback</code> and the
        class of each route are the author's, from SKILL.md at publish.
      </p>
      <div className="filters">
        <label>name{" "}
          <select aria-label="name" value={name ?? ""} onChange={(e) => navigate({ page: "governance", name: e.target.value || undefined })}>
            <option value="">any</option>
            {names.map((n) => <option key={n} value={n}>{n}</option>)}
            {name && !names.includes(name) && <option value={name}>{name}</option>}
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
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {!error && queries === null && <p className="muted">Loading the queries…</p>}
      {queries?.map((q) => <QueryList key={q.query} query={q} name={name} window={window} limit={limit} onRemoved={reload} />)}
      {queries !== null && <AddQuery onStored={reload} />}
    </article>
  );
}

type Saving = { kind: "idle" } | { kind: "busy" } | { kind: "unsupported"; message: string } | { kind: "error"; message: string };

/** Keep a query of your own: it runs on the server read-only, with the same parameters the built-ins get, and
 *  appears in the list above. Only a backend with a query language (Neo4j) can keep one. */
function AddQuery({ onStored }: { onStored: () => void }) {
  const [query, setQuery] = useState("");
  const [description, setDescription] = useState("");
  const [cypher, setCypher] = useState("");
  const [saving, setSaving] = useState<Saving>({ kind: "idle" });
  const ready = /^[a-z0-9]+(-[a-z0-9]+)*$/.test(query) && cypher.trim().length > 0 && saving.kind !== "busy";

  const store = () => {
    setSaving({ kind: "busy" });
    api.storeGovernanceQuery(query, { description, cypher })
      .then(() => { setSaving({ kind: "idle" }); setQuery(""); setDescription(""); setCypher(""); onStored(); })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 501) setSaving({ kind: "unsupported", message: e.message });
        else setSaving({ kind: "error", message: describe(e) });
      });
  };

  return (
    <section className="query add-query" data-testid="add-query" data-state={saving.kind}>
      <h2>Add a query</h2>
      <p className="muted">
        Cypher over the catalog and the runs, kept on the server and run read-only whenever this page asks. It may use
        <code> $name</code>, <code>$window</code>, <code>$limit</code>, <code>$repeats</code> and <code>$ids</code> (the
        resolved revisions) like the built-in queries. Needs the Neo4j backend.
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
      {saving.kind === "unsupported" && (
        <p className="muted small" data-testid="needs-graph">
          <span className="status-tag">needs the Neo4j backend</span> {saving.message}
        </p>
      )}
    </section>
  );
}

type Answer =
  | { kind: "loading" }
  | { kind: "rows"; rows: GovernanceRow[] }
  | { kind: "unsupported"; message: string }
  | { kind: "error"; message: string };

function QueryList({ query, name, window, limit, onRemoved }:
                   { query: GovernanceQuery; name?: string; window: number; limit: number; onRemoved: () => void }) {
  const [answer, setAnswer] = useState<Answer>({ kind: "loading" });
  const [removing, setRemoving] = useState<string | null>(null);   // an error message, or null

  const remove = () => {
    setRemoving(null);
    api.removeGovernanceQuery(query.query).then(onRemoved).catch((e: unknown) => setRemoving(describe(e)));
  };

  useEffect(() => {
    let live = true;
    setAnswer({ kind: "loading" });
    api.governanceQuery(query.query, { name, window, limit })
      .then((rows) => { if (live) setAnswer({ kind: "rows", rows }); })
      .catch((e: unknown) => {
        if (!live) return;
        // A 501 is the backend declining, not a fault: the filesystem backend has no graph to ask.
        if (e instanceof ApiError && e.status === 501) setAnswer({ kind: "unsupported", message: e.message });
        else setAnswer({ kind: "error", message: describe(e) });
      });
    return () => { live = false; };
  }, [query.query, name, window, limit]);

  return (
    <section className="query" data-testid="governance-query" data-query={query.query} data-state={answer.kind}
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
      {answer.kind === "error" && <p className="error" role="alert">{answer.message}</p>}
      {answer.kind === "unsupported" && (
        <p className="muted" data-testid="needs-graph">
          <span className="status-tag">needs the Neo4j backend</span> {answer.message}
        </p>
      )}
      {answer.kind === "rows" && answer.rows.length === 0 && <p className="muted" data-testid="no-rows">Nothing to report.</p>}
      {answer.kind === "rows" && answer.rows.length > 0 && <Rows rows={query.query === "manual-decisions" ? withResolvers(answer.rows) : answer.rows} />}
    </section>
  );
}

/** The resolver breakdown of a manual-decisions row: of the step's decisions, how many the client's decision
 *  model answered and how many were answered by hand. */
function withResolvers(rows: GovernanceRow[]): GovernanceRow[] {
  return rows.map((row) => {
    const decided = Number(row.decided), manual = Number(row.manual);
    return Number.isFinite(decided) && Number.isFinite(manual)
      ? { ...row, resolvers: { typesafe: decided - manual, manual } } : row;
  });
}

/** Rows are flat; the columns are the keys in order of first appearance. */
function Rows({ rows }: { rows: GovernanceRow[] }) {
  const columns: string[] = [];
  for (const row of rows) for (const key of Object.keys(row)) if (!columns.includes(key)) columns.push(key);
  return (
    <table className="compact" aria-label="rows">
      <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} data-testid="governance-row" data-name={cell(row.name)} data-step={cell(row.step)} data-question={cell(row.question)}
              data-resolver={cell(row.resolver)} data-router={cell(row.router)} data-reason={cell(row.reason)} data-code={cell(row.code)}
              data-class={cell(row.source_class)}>
            {columns.map((c) => <td key={c} className={typeof row[c] === "number" ? "num" : undefined}>{render(c, row[c], row)}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function cell(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function render(column: string, value: unknown, row: GovernanceRow): React.ReactNode {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  if (column === "resolvers" && typeof value === "object") {
    const { typesafe, manual } = value as { typesafe: number; manual: number };
    const total = typesafe + manual || 1;
    return (
      <span data-testid="resolver-breakdown" data-typesafe={typesafe} data-manual={manual}>
        <span className="resolver-bar" aria-hidden="true">
          <span className="model" style={{ width: `${(100 * typesafe) / total}%` }} />
          <span className="manual" style={{ width: `${(100 * manual) / total}%` }} />
        </span>{" "}
        model {typesafe} · by hand {manual}
      </span>
    );
  }
  if (column === "resolver" && typeof value === "string") return <span className="status-tag" data-testid="resolver">{value}</span>;
  if (column === "reason" && typeof value === "string") {
    const why = value === "low" ? "the confidence was below the bound" : value === "absent" ? "no confidence was recorded (answered by hand)" : value === "null" ? "the confidence was null" : "";
    return <span className="status-tag check-fired" data-testid="reason" title={why}>{value}</span>;
  }
  if (column === "source_class" && typeof value === "string") return <span className={`status-tag class-${value}`} data-testid="source-class">{value}</span>;
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
  if (column === "stderr" && typeof value === "string") return value ? <pre className="stderr" data-testid="stderr">{value}</pre> : <span className="muted">empty</span>;
  if (column === "exit_code" && typeof value === "number") return <code data-testid="exit-code">{value}</code>;
  if (column === "name" && typeof value === "string") {
    const ref = typeof row.revision === "string" ? `${value}@${row.revision}` : value;
    return <a href={href({ page: "procedure", ref })}><code>{value}</code></a>;
  }
  if (column === "revision" && typeof value === "string") return <code>{value.slice(0, 8)}</code>;
  if (column === "rate" && typeof value === "number") return `${Math.round(value * 100)}%`;
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "string") return column === "step" || column === "question" || column === "script" || column === "router" || column === "code" ? <code>{value}</code> : value;
  if (Array.isArray(value)) return value.map((v, i) => <span key={i}>{i ? ", " : ""}<code>{String(v)}</code></span>);
  return <code>{JSON.stringify(value)}</code>;
}
