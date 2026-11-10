import { useEffect, useState } from "react";

// Hash routes, so the console's process serves one page with no fallback rule. In folder mode only
// #/ (the folder's procedure), #/run and #/runs apply; the others need a server.
//   #/                          catalog (folder mode: the folder's procedure)
//   #/p/<ref>[?view=]           a procedure: its steps (the step graph as control flow, data flow or run
//                               traffic, or the card canvas: view=control|data|traffic|cards), header, revisions
//   #/p/<ref>/files[/<path>]    source: procedure.aip and the bundle's files, one open
//   #/p/<name>/diff[/<a>..<b>]  diff between two revisions of a name
//   #/run[/<ref>]               run console: pick a procedure, then drive it through the CLI
//   #/runs[?name=&status=&agent=&session=&user=&draft=]   history: the runs the server holds
//   #/runs/<id>                 one run's record
//   #/audit[?name=]             the audit queries of GET /audit
//   #/server                    the console's server, and the bearer token for this browser
//
// <ref> is `name`, `name@rev`, `name@latest`, or `bundle:<bundle id>` for a bundle the store holds
// with no revision (a draft), which has no name to resolve.
export type Route =
  | { page: "catalog" }
  | { page: "procedure"; ref: string; view?: string }
  | { page: "source"; ref: string; path?: string }
  | { page: "diff"; name: string; a?: string; b?: string }
  | { page: "run"; ref?: string }
  | { page: "runs"; name?: string; status?: string; agent?: string; session?: string; user?: string; draft?: boolean }
  | { page: "run-detail"; id: string }
  | { page: "audit"; name?: string }
  | { page: "server" }
  | { page: "missing"; hash: string };

const decodePath = (p: string) => p.split("/").map(decodeURIComponent).join("/");
const encodePath = (p: string) => p.split("/").map(encodeURIComponent).join("/");

/** The reference of a bundle by id, and back. */
export const bundleRef = (bundleId: string) => `bundle:${bundleId}`;
export const bundleOf = (ref: string): string | null => (ref.startsWith("bundle:") ? ref.slice(7) : null);

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "").replace(/^\/+/, "");
  if (path === "") return { page: "catalog" };
  let m = /^p\/([^/?]+)(?:\?(.*))?$/.exec(path);
  if (m) return { page: "procedure", ref: decodeURIComponent(m[1]), view: new URLSearchParams(m[2] ?? "").get("view") ?? undefined };
  m = /^p\/([^/]+)\/files(?:\/(.+))?$/.exec(path);
  if (m) return { page: "source", ref: decodeURIComponent(m[1]), path: m[2] ? decodePath(m[2]) : undefined };
  m = /^p\/([^/@]+)\/diff(?:\/([^.]+)\.\.([^.]+))?$/.exec(path);
  if (m) {
    return { page: "diff", name: decodeURIComponent(m[1]),
             a: m[2] ? decodeURIComponent(m[2]) : undefined, b: m[3] ? decodeURIComponent(m[3]) : undefined };
  }
  m = /^run(?:\/([^/]+))?$/.exec(path);
  if (m) return { page: "run", ref: m[1] ? decodeURIComponent(m[1]) : undefined };
  m = /^runs(?:\?(.*))?$/.exec(path);
  if (m) {
    const q = new URLSearchParams(m[1] ?? "");
    const draft = q.get("draft");
    return { page: "runs", name: q.get("name") ?? undefined, status: q.get("status") ?? undefined, agent: q.get("agent") ?? undefined,
             session: q.get("session") ?? undefined, user: q.get("user") ?? undefined,
             draft: draft === "true" ? true : draft === "false" ? false : undefined };
  }
  m = /^runs\/([^/?]+)$/.exec(path);
  if (m) return { page: "run-detail", id: decodeURIComponent(m[1]) };
  m = /^audit(?:\?(.*))?$/.exec(path);
  if (m) return { page: "audit", name: new URLSearchParams(m[1] ?? "").get("name") ?? undefined };
  if (path === "server") return { page: "server" };
  return { page: "missing", hash };
}

export function href(route: Route): string {
  switch (route.page) {
    case "catalog": return "#/";
    case "procedure": return `#/p/${encodeURIComponent(route.ref)}${route.view ? "?view=" + encodeURIComponent(route.view) : ""}`;
    case "source":
      return `#/p/${encodeURIComponent(route.ref)}/files${route.path ? "/" + encodePath(route.path) : ""}`;
    case "diff": {
      const pair = route.a && route.b ? `/${encodeURIComponent(route.a)}..${encodeURIComponent(route.b)}` : "";
      return `#/p/${encodeURIComponent(route.name)}/diff${pair}`;
    }
    case "run": return `#/run${route.ref ? "/" + encodeURIComponent(route.ref) : ""}`;
    case "runs": {
      const q = new URLSearchParams();
      if (route.name) q.set("name", route.name);
      if (route.status) q.set("status", route.status);
      if (route.agent) q.set("agent", route.agent);
      if (route.session) q.set("session", route.session);
      if (route.user) q.set("user", route.user);
      if (route.draft !== undefined) q.set("draft", String(route.draft));
      const qs = q.toString();
      return `#/runs${qs ? "?" + qs : ""}`;
    }
    case "run-detail": return `#/runs/${encodeURIComponent(route.id)}`;
    case "audit": return `#/audit${route.name ? "?name=" + encodeURIComponent(route.name) : ""}`;
    case "server": return "#/server";
    case "missing": return route.hash;
  }
}

export function navigate(route: Route): void {
  window.location.hash = href(route);
}

/** A hash with no leading slash (`#step-triage`) names an element on the current page, not a route. */
const isAnchor = (hash: string) => /^#[^/]/.test(hash);

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    // An in-page anchor must not become a route: the page would unmount and show "No page at", and
    // the element it names would be gone before the browser could scroll to it. Clicks on such links
    // scroll instead and leave the route's hash in the address bar; a hash typed in by hand keeps the
    // current route.
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const link = (e.target as Element | null)?.closest("a");
      const target = link?.getAttribute("href");
      if (!target || !isAnchor(target)) return;
      e.preventDefault();
      document.getElementById(decodeURIComponent(target.slice(1)))?.scrollIntoView({ block: "start" });
    };
    const onChange = () => { if (!isAnchor(window.location.hash)) setRoute(parseHash(window.location.hash)); };
    document.addEventListener("click", onClick);
    window.addEventListener("hashchange", onChange);
    return () => { document.removeEventListener("click", onClick); window.removeEventListener("hashchange", onChange); };
  }, []);
  return route;
}
