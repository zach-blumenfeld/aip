import { useEffect, useState } from "react";

// Hash routes, so the console's process serves one page with no fallback rule. In folder mode only
// #/run (and #/, which shows it) apply; the others need a server.
//                         #/                          catalog
//                         #/p/<ref>                   procedure page, ref = name or name@rev
//                         #/p/<ref>/files[/<path>]    source: the manifest, and one file open
//                         #/p/<name>/diff[/<a>..<b>]  diff between two revisions of name
//                         #/run[/<ref>]               run console: pick a procedure, then drive it through the CLI
//                         #/runs[?name=&status=]      history: the runs the server persisted
//                         #/runs/<id>                 one run replayed as a trace over the step graph
//                         #/governance[?name=]        the corpus queries of GET /governance as lists
//                         #/studio[?import=<ref>|?new] build a procedure in the browser, exported as a skill zip;
//                                                     import a revision into a new draft, or start a blank one
//                         #/server                    the console's server, and the bearer token for this browser
export type Route =
  | { page: "catalog" }
  | { page: "procedure"; ref: string }
  | { page: "source"; ref: string; path?: string }
  | { page: "diff"; name: string; a?: string; b?: string }
  | { page: "run"; ref?: string }
  | { page: "runs"; name?: string; status?: string }
  | { page: "run-detail"; id: string }
  | { page: "governance"; name?: string }
  | { page: "studio"; import?: string; fresh?: boolean }
  | { page: "server" }
  | { page: "missing"; hash: string };

const decodePath = (p: string) => p.split("/").map(decodeURIComponent).join("/");
const encodePath = (p: string) => p.split("/").map(encodeURIComponent).join("/");

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "").replace(/^\/+/, "");
  if (path === "") return { page: "catalog" };
  let m = /^p\/([^/]+)$/.exec(path);
  if (m) return { page: "procedure", ref: decodeURIComponent(m[1]) };
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
    return { page: "runs", name: q.get("name") ?? undefined, status: q.get("status") ?? undefined };
  }
  m = /^runs\/([^/?]+)$/.exec(path);
  if (m) return { page: "run-detail", id: decodeURIComponent(m[1]) };
  m = /^governance(?:\?(.*))?$/.exec(path);
  if (m) return { page: "governance", name: new URLSearchParams(m[1] ?? "").get("name") ?? undefined };
  m = /^studio(?:\?(.*))?$/.exec(path);
  if (m) {
    const q = new URLSearchParams(m[1] ?? "");
    return { page: "studio", import: q.get("import") ?? undefined, fresh: q.has("new") || undefined };
  }
  if (path === "server") return { page: "server" };
  return { page: "missing", hash };
}

export function href(route: Route): string {
  switch (route.page) {
    case "catalog": return "#/";
    case "procedure": return `#/p/${encodeURIComponent(route.ref)}`;
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
      const qs = q.toString();
      return `#/runs${qs ? "?" + qs : ""}`;
    }
    case "run-detail": return `#/runs/${encodeURIComponent(route.id)}`;
    case "governance": return `#/governance${route.name ? "?name=" + encodeURIComponent(route.name) : ""}`;
    case "studio": return route.import ? `#/studio?import=${encodeURIComponent(route.import)}` : route.fresh ? "#/studio?new" : "#/studio";
    case "server": return "#/server";
    case "missing": return route.hash;
  }
}

export function navigate(route: Route): void {
  window.location.hash = href(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
