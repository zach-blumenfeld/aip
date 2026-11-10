import { Catalog } from "./views/Catalog";
import { FolderProcedure, Procedure } from "./views/Procedure";
import { Source } from "./views/Source";
import { Diff } from "./views/Diff";
import { Run } from "./views/Run";
import { Studio } from "./views/Studio";
import { RunPage, Runs } from "./views/History";
import { Audit } from "./views/Audit";
import { Server } from "./views/Server";
import { consoleConfig, isFolderMode } from "./api/console";
import { href, useRoute, type Route } from "./router";

export function App() {
  const route = useRoute();
  const folder = isFolderMode();
  return (
    <>
      <header>
        <a href={href({ page: "catalog" })}><strong>aip console</strong></a>
        <nav className="top-nav">
          <a href={href({ page: "catalog" })}>{folder ? "procedure" : "catalog"}</a>
          {!folder && <a href={href({ page: "studio" })}>studio</a>}
          <a href={href({ page: "run" })}>run</a>
          <a href={href({ page: "runs" })}>history</a>
          {!folder && <a href={href({ page: "audit" })}>audit</a>}
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
    case "procedure": return <Procedure reference={route.ref} view={route.view} />;
    case "source": return <Source reference={route.ref} path={route.path} />;
    case "diff": return <Diff name={route.name} a={route.a} b={route.b} />;
    case "run": return <Run reference={route.ref} />;
    case "studio": return <Studio key={route.ref ?? ""} reference={route.ref} />;
    case "runs": return <Runs route={route} />;
    case "run-detail": return <RunPage id={route.id} />;
    case "audit": return <Audit name={route.name} />;
    case "server": return <Server />;
    case "missing": return <p className="error">No page at <code>{route.hash}</code>.</p>;
  }
}

/** A folder has no server behind it: its procedure, local runs of it, and this machine's run files of it. */
function FolderPage({ route }: { route: Route }) {
  if (route.page === "catalog") return <FolderProcedure />;
  if (route.page === "run") return <Run />;
  if (route.page === "runs") return <Runs route={route} />;
  if (route.page === "run-detail") return <RunPage id={route.id} />;
  return (
    <p className="muted" data-testid="folder-mode">
      This console runs the folder <code>{consoleConfig().folder}</code> locally, with no server: there is no catalog, source
      view or audit. Start it with <code>--server URL</code> for those; here you can read the <a href={href({ page: "catalog" })}>procedure</a>,{" "}
      <a href={href({ page: "run" })}>run</a> it and see its <a href={href({ page: "runs" })}>runs</a>.
    </p>
  );
}
