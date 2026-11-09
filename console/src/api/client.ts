import { consoleConfig } from "./console";
import type {
  ApiErrorBody, CatalogEntry, FileEntry, GovernanceQuery, GovernanceRow, ProcedureInfo, PublishResult, RunDetail, RunSummary,
  SearchHit, ValidationIssue,
} from "./types";

const TOKEN_KEY = "aip.token";

/** The server the console was started for (`aip-console --server URL`, else `aip config`); the page calls it
 *  directly, and the runs the console starts use the same one. Empty in folder mode, where nothing calls it. */
export function serverUrl(): string {
  return consoleConfig().server ?? "";
}

/** The bearer token, kept in sessionStorage: the design (§11) says never beyond the session. */
export function token(): string {
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string | null): void {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, public kind: string, message: string, public location?: string,
              /** A 422 `invalid_skill` from publish: the validator's issues. */
              public issues: ValidationIssue[] = []) {
    super(message);
  }
}

/** Fetch with the bearer token; a non-2xx response becomes an ApiError from the envelope. */
async function send(path: string, init: RequestInit = {}, accept = "application/json"): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", accept);
  if (init.body) headers.set("Content-Type", "application/json");
  const bearer = token();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);
  const res = await fetch(serverUrl() + path, { ...init, headers });
  if (!res.ok) {
    let body: ApiErrorBody | null = null;
    try { body = (await res.json()) as ApiErrorBody; } catch { /* not an envelope */ }
    const e = body?.error;
    throw new ApiError(res.status, e?.kind ?? "http_error", e?.message ?? res.statusText, e?.location, e?.issues ?? []);
  }
  return res;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await (await send(path, init)).json()) as T;
}

/** One file of a revision: the raw bytes and the media type the server guessed from the path. */
export interface FileBytes { bytes: Uint8Array; mediaType: string }

/** A file path as URL path segments: slashes kept, each segment encoded. */
export function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export const api = {
  catalog: () => request<CatalogEntry[]>("/catalog"),
  search: (q: string, limit = 20) =>
    request<SearchHit[]>(`/catalog/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  /** `ref` is a name, `name@rev`, or `name@latest`. */
  info: (ref: string) => request<ProcedureInfo>(`/catalog/${encodeURIComponent(ref)}`),
  /** The file manifest of a revision: path, size, sha256, mode. */
  files: (ref: string) => request<FileEntry[]>(`/catalog/${encodeURIComponent(ref)}/files`),
  /** The raw bytes of one file of a revision. */
  file: async (ref: string, path: string): Promise<FileBytes> => {
    const res = await send(`/catalog/${encodeURIComponent(ref)}/files/${encodePath(path)}`, {}, "*/*");
    return { bytes: new Uint8Array(await res.arrayBuffer()), mediaType: res.headers.get("Content-Type") ?? "application/octet-stream" };
  },

  /** Publish a skill's files (publish scope): the server validates them and names the skill from SKILL.md, so an
   *  existing name gets a new revision, and the same bytes the revision already there. 422 `invalid_skill` carries
   *  the validator's issues (ApiError.issues). */
  publish: (files: { path: string; bytes: Uint8Array; mode: number }[]) =>
    request<PublishResult>("/catalog", {
      method: "POST",
      body: JSON.stringify({ files: files.map((f) => ({ path: f.path, bytes_b64: base64(f.bytes), mode: f.mode })) }),
    }),

  // Runs are driven by the `aip` CLI the console spawns (api/console.ts); the page only reads them.

  runs: (filter: { name?: string; status?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (filter.name) q.set("name", filter.name);
    if (filter.status) q.set("status", filter.status);
    if (filter.limit) q.set("limit", String(filter.limit));
    const qs = q.toString();
    return request<RunSummary[]>(`/runs${qs ? "?" + qs : ""}`);
  },
  run: (id: string) => request<RunDetail>(`/runs/${encodeURIComponent(id)}`),

  // Governance (§7): the publish scope for pin and retire; read for the corpus queries.
  /** Pin `revision` as what the bare name resolves to; null clears the pin (latest live again). */
  pin: (name: string, revision: string | null) =>
    request<{ name: string; pinned: string | null }>(`/catalog/${encodeURIComponent(name)}/pin`, { method: "POST", body: JSON.stringify({ revision }) }),
  retire: (name: string, revision: string) =>
    request<{ name: string; retired: string }>(`/catalog/${encodeURIComponent(name)}/retire`, { method: "POST", body: JSON.stringify({ revision }) }),
  governance: () => request<GovernanceQuery[]>("/governance"),
  governanceQuery: (query: string, filter: { name?: string; window?: number; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (filter.name) q.set("name", filter.name);
    if (filter.window) q.set("window", String(filter.window));
    if (filter.limit) q.set("limit", String(filter.limit));
    const qs = q.toString();
    return request<GovernanceRow[]>(`/governance/${encodeURIComponent(query)}${qs ? "?" + qs : ""}`);
  },
  /** Keep a query of your own on the server (replacing one of that name); 501 on a backend with no query language. */
  storeGovernanceQuery: (query: string, body: { description: string; cypher: string }) =>
    request<GovernanceQuery>(`/governance/${encodeURIComponent(query)}`, { method: "PUT", body: JSON.stringify(body) }),
  removeGovernanceQuery: (query: string) =>
    request<{ query: string; removed: boolean }>(`/governance/${encodeURIComponent(query)}`, { method: "DELETE" }),
};

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
