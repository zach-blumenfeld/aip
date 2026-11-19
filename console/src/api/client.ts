import { consoleConfig, wakeServer } from "./console";
import type {
  ApiErrorBody, AuditQuery, AuditRow, BundleFile, BundleGraph, BundleRow, CatalogEntry, Description, RunRecord, RunSummary, SearchHit,
} from "./types";

const TOKEN_KEY = "aip.token";

/** The server the console was started for (`aip-console --server URL`, else `aip config`); the page calls it
 *  directly, and the runs the console starts are recorded on the same one. Empty in folder mode, where nothing calls it. */
export function serverUrl(): string {
  return consoleConfig().server ?? "";
}

/** The bearer token, kept in sessionStorage: never beyond the session. */
export function token(): string {
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  kind: string;
  location?: string;

  constructor(status: number, kind: string, message: string, location?: string) {
    super(message);
    this.status = status;
    this.kind = kind;
    this.location = location;
  }
}

/** `kind: message` for an API error, the text of anything else. */
export function describe(e: unknown): string {
  return e instanceof ApiError ? `${e.kind}: ${e.message}` : e instanceof Error ? e.message : String(e);
}

/** Fetch with the bearer token; a non-2xx response becomes an ApiError from the envelope. A local server stops
 *  when idle (aip docs/server-design.md, The local server), so a request nothing answers asks the console's
 *  process to wake it and is sent once more. */
async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  const bearer = token();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);
  let res: Response;
  try {
    res = await fetch(serverUrl() + path, { ...init, headers });
  } catch (e) {
    if (!(await wakeServer())) throw new ApiError(0, "unreachable", `nothing answers at ${serverUrl()} (${e instanceof Error ? e.message : String(e)})`);
    res = await fetch(serverUrl() + path, { ...init, headers });
  }
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try { body = (await res.json()) as ApiErrorBody; } catch { /* not an envelope */ }
    const error = body?.error;
    throw new ApiError(res.status, error?.kind ?? "http_error", error?.message ?? res.statusText, error?.location);
  }
  return res;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await (await send(path, init)).json()) as T;
}

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") q.set(key, String(value));
  }
  const text = q.toString();
  return text ? `?${text}` : "";
}

/** Which runs: every field optional. `draft` true is the runs of bundles with no revision, false of published ones. */
export interface RunFilter {
  name?: string;
  status?: string;
  agent?: string;
  session?: string;
  user?: string;
  draft?: boolean;
  limit?: number;
}

/** An audit query's parameters (aip docs/server-design.md, Audit). */
export interface AuditFilter extends RunFilter {
  window?: number;
  repeats?: number;
  key?: string;
}

const enc = encodeURIComponent;

export const api = {
  catalog: () => request<CatalogEntry[]>("/catalog"),
  search: (q: string, limit = 20) => request<SearchHit[]>(`/catalog/search${query({ q, limit })}`),
  /** `ref` is a name, `name@rev`, or `name@latest`. */
  info: (ref: string) => request<Description>(`/catalog/${enc(ref)}`),
  /** The revision's graph, with the source and the files' text. */
  graph: (ref: string) => request<BundleGraph>(`/catalog/${enc(ref)}/graph`),
  /** Every bundle the store holds; `drafts` true for the ones with no revision. */
  bundles: (drafts?: boolean) => request<BundleRow[]>(`/bundles${query({ drafts })}`),
  bundle: (bundleId: string) => request<Description>(`/bundles/${enc(bundleId)}`),
  bundleGraph: (bundleId: string) => request<BundleGraph>(`/bundles/${enc(bundleId)}/graph`),

  // Runs are driven by the `aip` CLI the console spawns (api/console.ts); the page only reads them.
  runs: (filter: RunFilter = {}) => request<RunSummary[]>(`/runs${query({ ...filter })}`),
  run: (id: string) => request<RunRecord>(`/runs/${enc(id)}`),

  /** Pin `revision` as what the bare name resolves to; null clears the pin. Needs the publish scope. */
  pin: (name: string, revision: string | null) =>
    request<{ name: string; pinned: string | null }>(`/catalog/${enc(name)}/pin`, { method: "POST", body: JSON.stringify({ revision }) }),
  retire: (name: string, revision: string) =>
    request<{ name: string; revision: string; retired: boolean }>(`/catalog/${enc(name)}/retire`, { method: "POST", body: JSON.stringify({ revision }) }),

  audit: () => request<AuditQuery[]>("/audit"),
  auditQuery: (name: string, filter: AuditFilter = {}) => request<AuditRow[]>(`/audit/${enc(name)}${query({ ...filter })}`),
  /** Keep a query of your own on the server (replacing one of that name). Needs the publish scope. */
  storeAuditQuery: (name: string, body: { description: string; cypher: string }) =>
    request<AuditQuery>(`/audit/${enc(name)}`, { method: "PUT", body: JSON.stringify(body) }),
  removeAuditQuery: (name: string) => request<{ query: string; deleted: boolean }>(`/audit/${enc(name)}`, { method: "DELETE" }),
};

/** The text of `procedure.aip`, off the graph's `Procedure` node. */
export function sourceOf(bundle: BundleGraph): string {
  const procedure = bundle.graph.nodes.find((n) => n.labels.includes("Procedure"));
  const source = procedure?.properties.source;
  return typeof source === "string" ? source : "";
}

/** Everything the bundle was compiled from: `procedure.aip` first (it has no hash of its own in the graph), then its files. */
export function allFiles(bundle: BundleGraph): BundleFile[] {
  const source = sourceOf(bundle);
  return [{ path: "procedure.aip", size: new TextEncoder().encode(source).length, sha256: "", mode: 0o644, text: source, base64: null },
          ...filesOf(bundle)];
}

/** The graph of a reference: a revision's, or for `bundle:<id>` the bundle's by id. */
export function graphOf(ref: string): Promise<BundleGraph> {
  return ref.startsWith("bundle:") ? api.bundleGraph(ref.slice(7)) : api.graph(ref);
}

/** The bundle's files, off the graph's `File` nodes, by path. */
export function filesOf(bundle: BundleGraph): BundleFile[] {
  const text = (v: unknown) => (typeof v === "string" ? v : null);
  return bundle.graph.nodes.filter((n) => n.labels.includes("File")).map((n) => ({
    path: String(n.properties.path ?? ""), size: Number(n.properties.size ?? 0), sha256: String(n.properties.sha256 ?? ""),
    mode: Number(n.properties.mode ?? 0o644), text: text(n.properties.text), base64: text(n.properties.base64),
  })).sort((a, b) => a.path.localeCompare(b.path));
}
