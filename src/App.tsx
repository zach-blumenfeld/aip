import { Catalog } from "./views/Catalog";
import { Procedure } from "./views/Procedure";
import { Source } from "./views/Source";
import { Diff } from "./views/Diff";
import { Run } from "./views/Run";
import { RunPage, Runs } from "./views/History";
import { Governance } from "./views/Governance";
import { Server } from "./views/Server";
import { Studio } from "./views/Studio";
import { consoleConfig, isFolderMode } from "./api/console";
import { href, useRoute, type Route } from "./router";

export function App() {
  const route = useRoute();
  const folder = isFolderMode();
  return (
    <>
      <header>
        <a href={href(folder ? { page: "run" } : { page: "catalog" })}><strong>aip console</strong></a>
        <nav className="top-nav">
          {!folder && <a href={href({ page: "catalog" })}>catalog</a>}
          <a href={href({ page: "run" })}>run</a>
          {!folder && <a href={href({ page: "runs" })}>history</a>}
          {!folder && <a href={href({ page: "governance" })}>governance</a>}
          <a href={href({ page: "studio" })}>studio</a>
        </nav>
        {folder ? <span className="muted server-link" data-testid="console-target">folder {consoleConfig().folder}</span>
                : <a className="muted server-link" data-testid="console-target" href={href({ page: "server" })}>{consoleConfig().server}</a>}
      </header>
      <main>{folder ? <FolderPage route={route} /> : <ServerPage route={route} />}</main>
    </>
  );
}

function ServerPage({ route }: { route: Route }) {
  switch (route.page) {
    case "catalog": return <Catalog />;
    case "procedure": return <Procedure reference={route.ref} />;
    case "source": return <Source reference={route.ref} path={route.path} />;
    case "diff": return <Diff name={route.name} a={route.a} b={route.b} />;
    case "run": return <Run reference={route.ref} />;
    case "runs": return <Runs name={route.name} status={route.status} />;
    case "run-detail": return <RunPage id={route.id} />;
    case "governance": return <Governance name={route.name} />;
    case "studio": return <Studio importRef={route.import} fresh={route.fresh} />;
    case "server": return <Server />;
    case "missing": return <p className="error">No page at <code>{route.hash}</code>.</p>;
  }
}

/** A folder has no server behind it: no catalog, history or governance, only local runs of the folder. */
function FolderPage({ route }: { route: Route }) {
  if (route.page === "studio") return <Studio fresh={route.fresh} />;
  if (route.page === "run" || route.page === "catalog") return <Run />;
  return (
    <p className="muted" data-testid="folder-mode">
      This console runs the folder <code>{consoleConfig().folder}</code> locally, with no server: there is no catalog,
      history or governance. Start it with <code>--server URL</code> for those; <a href={href({ page: "run" })}>run</a> the folder here.
    </p>
  );
}
