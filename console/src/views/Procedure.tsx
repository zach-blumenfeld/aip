import { useEffect, useState } from "react";
import { api, describe, filesOf, sourceOf } from "../api/client";
import { consoleConfig, describeProcedure, folderGraph, type Diagnostic, type FolderGraph } from "../api/console";
import type { BundleGraph, CatalogEntry, Description } from "../api/types";
import { Code } from "../highlight/Code.tsx";
import { bundleOf, href, navigate } from "../router";
import { DraftBadge, when } from "./Record";
import { isStepsView, Steps, type StepsView } from "./Steps";

/** A procedure the server holds: a revision of a published name, or a draft bundle by its id. Its steps are
 *  drawn from the bundle's own graph (the step graph in the mode `view` names, which the address carries);
 *  the header, the inputs and the result are what `aip info` prints. */
export function Procedure({ reference, view }: { reference: string; view?: string }) {
  const [about, setAbout] = useState<Description | null>(null);
  const [bundle, setBundle] = useState<BundleGraph | null>(null);
  const [entry, setEntry] = useState<CatalogEntry | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped after pin or retire: the fetches run again, the page stays up meanwhile.
  const [version, setVersion] = useState(0);
  const bundleId = bundleOf(reference);

  useEffect(() => { setAbout(null); setBundle(null); setEntry(null); }, [reference]);

  useEffect(() => {
    setError(null);
    const fail = (e: unknown) => setError(describe(e));
    (bundleId ? api.bundle(bundleId) : api.info(reference)).then(setAbout).catch(fail);
    (bundleId ? api.bundleGraph(bundleId) : api.graph(reference)).then(setBundle).catch(fail);
  }, [reference, bundleId, version]);

  const name = about?.name;
  useEffect(() => {
    if (!name) return;
    api.catalog().then((all) => setEntry(all.find((c) => c.name === name) ?? null)).catch(() => setEntry(null));
  }, [name, version]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (about === null) return <p className="muted">Loading {reference}…</p>;

  const draft = about.draft === true || !about.revision;
  const exact = draft ? reference : `${about.name}@${about.revision}`;
  // Revisions are newest first; the one after the current is the one published before it.
  const revisions = entry?.revisions.map((r) => r.revision) ?? [];
  const previous = about.revision ? revisions[revisions.indexOf(about.revision) + 1] : undefined;

  return (
    <article className="procedure">
      <nav className="crumbs"><a href={href({ page: "catalog" })}>catalog</a> / <code>{about.name}</code></nav>
      <h1>
        {about.name}
        {about.revision && <span className="muted rev"> @{about.revision}{about.retired ? " (retired)" : ""}</span>}
        {" "}<DraftBadge draft={draft} />
      </h1>
      <p className="prose">{about.description}</p>
      {draft && (
        <p className="muted small" data-testid="draft-note">
          A draft: the server holds this bundle with no revision, because a run of a folder or a file was recorded against it, or the studio saved it.
          It is not in the catalog and no name resolves to it; <code>aip publish</code> (or Publish in the studio) gives it a revision.
        </p>
      )}
      <p className="links">
        <a href={href({ page: "source", ref: exact })}>source</a>
        {bundle && <span className="muted"> · {filesOf(bundle).length + 1} files</span>}
        {previous && about.revision && <> · <a href={href({ page: "diff", name: about.name, a: previous, b: about.revision })}>diff with previous</a></>}
        {!draft && <>{" · "}<a href={href({ page: "run", ref: exact })}>run</a></>}
        {" · "}<a href={href({ page: "studio", ref: exact })} data-testid="open-studio">edit in the studio</a>
        {" · "}<a href={href({ page: "runs", name: about.name, draft: draft ? true : undefined })}>history</a>
        <span className="muted"> · bundle <code title={about.bundle_id}>{about.bundle_id.slice(0, 12)}</code></span>
      </p>

      <div className="steps-grid">
        {bundle
          ? <Steps graph={bundle.graph} source={sourceOf(bundle)} name={about.name} bundleId={about.bundle_id}
                   view={isStepsView(view) ? view : "control"} onView={(v) => navigate({ page: "procedure", ref: reference, view: v === "control" ? undefined : v })} />
          : <section><h2>Steps</h2><p className="muted">Loading the graph…</p></section>}
        <About about={about} />
      </div>

      {!draft && entry && about.revision && (
        <Revisions entry={entry} current={about.revision} onChanged={() => setVersion((v) => v + 1)} />
      )}
    </article>
  );
}

/** Folder mode: the folder's procedure, compiled by the CLI on this machine each time the page is opened. */
export function FolderProcedure() {
  const [about, setAbout] = useState<Description | null>(null);
  const [compiled, setCompiled] = useState<FolderGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<StepsView>("control");

  useEffect(() => {
    folderGraph().then(setCompiled).catch((e: unknown) => setError(describe(e)));
    // A folder with errors has no description: the diagnostics below say why.
    describeProcedure().then(setAbout).catch(() => setAbout(null));
  }, []);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (compiled === null) return <p className="muted">Compiling {consoleConfig().folder}…</p>;

  return (
    <article className="procedure">
      <nav className="crumbs">folder <code>{consoleConfig().folder}</code></nav>
      <h1>{about?.name ?? "procedure.aip"} <span className="muted rev">folder</span></h1>
      {about && <p className="prose">{about.description}</p>}
      <p className="links">
        <a href={href({ page: "run" })}>run</a>{" · "}<a href={href({ page: "runs" })}>runs of this folder</a>
        {compiled.bundle_id && <span className="muted"> · compiles to bundle <code title={compiled.bundle_id}>{compiled.bundle_id.slice(0, 12)}</code></span>}
      </p>
      <Diagnostics diagnostics={compiled.diagnostics} />
      <div className="steps-grid">
        {compiled.graph
          ? <Steps graph={compiled.graph} source={compiled.source} name={about?.name ?? ""} bundleId={compiled.bundle_id} view={view} onView={setView} />
          : <section className="wide"><h2>Steps</h2><p className="muted">The folder does not compile, so there is no graph to draw. Its source:</p><Code text={compiled.source} aip /></section>}
        {about && <About about={about} />}
      </div>
    </article>
  );
}

function Diagnostics({ diagnostics }: { diagnostics: Diagnostic[] }) {
  if (diagnostics.length === 0) return null;
  return (
    <ul className="issues" data-testid="diagnostics">
      {diagnostics.map((d, i) => (
        <li key={i} data-severity={d.severity} data-code={d.code}>
          <code>{d.code}</code> {d.severity}{d.line !== null ? ` at line ${d.line}` : ""}: {d.message}
        </li>
      ))}
    </ul>
  );
}

/** What `aip info` says: when to use it, what it takes and returns, what the scripts need. */
function About({ about }: { about: Description }) {
  return (
    <div className="about">
      <section>
        <List title="Use when" items={about.use_when} />
        <List title="Do not use when" items={about.do_not_use_when} />
        <List title="Avoid" items={about.avoid} />
      </section>
      <section>
        <h2>Inputs</h2>
        <Keys keys={about.inputs} descriptions={about.input_descriptions} testid="inputs" />
        <h2>Result</h2>
        <Keys keys={about.result} testid="result" />
        <h2>Requires</h2>
        <p data-testid="requires">
          {about.requires?.interpreter
            ? <>Its scripts need <code>{about.requires.interpreter}{about.requires.version ? ` ${about.requires.version}` : ""}</code> on the machine that runs them.</>
            : <span className="muted">Nothing named.</span>}
        </p>
      </section>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <>
      <h2>{title}</h2>
      <ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </>
  );
}

function Keys({ keys, descriptions = {}, testid }: { keys: Record<string, string | null>; descriptions?: Record<string, string>; testid: string }) {
  const entries = Object.entries(keys ?? {});
  if (entries.length === 0) return <p className="muted" data-testid={testid}>None.</p>;
  return (
    <table className="compact" data-testid={testid}>
      <tbody>
        {entries.map(([key, type]) => (
          <tr key={key}><td><code>{key}</code></td><td><code>{type ?? "any"}</code></td><td>{descriptions[key] ?? ""}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

/** The name's revisions, with what the bare name resolves to, and pin and retire (the publish scope). */
function Revisions({ entry, current, onChanged }: { entry: CatalogEntry; current: string; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const act = (call: Promise<unknown>) => {
    setError(null);
    call.then(onChanged).catch((e: unknown) => setError(describe(e)));
  };
  return (
    <section className="governance-box" data-testid="revisions">
      <h2>Revisions</h2>
      <p className="muted small">
        The bare name <code>{entry.name}</code> runs {entry.resolves ? <>revision <code data-testid="resolves">{entry.resolves}</code></> : "nothing: every revision is retired"}
        {entry.pinned ? " (pinned)" : entry.resolves ? " (the latest)" : ""}. A retired revision still opens by <code>name@revision</code>, for the runs that name it.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      <table className="compact" aria-label="revisions">
        <thead><tr><th>revision</th><th>published</th><th>bundle</th><th></th><th></th></tr></thead>
        <tbody>
          {entry.revisions.map((r) => (
            <tr key={r.revision} data-testid="revision-row" data-revision={r.revision} data-retired={r.retired ? "true" : undefined}
                aria-current={r.revision === current ? "true" : undefined}>
              <td><a href={href({ page: "procedure", ref: `${entry.name}@${r.revision}` })}><code>{r.revision}</code></a></td>
              <td className="when">{when(r.published_at)}</td>
              <td><code title={r.bundle_id}>{r.bundle_id.slice(0, 12)}</code></td>
              <td>
                {r.revision === entry.pinned && <span className="status-tag" data-testid="pinned-tag">pinned</span>}
                {r.revision === entry.latest && <span className="status-tag"> latest</span>}
                {r.retired && <span className="status-tag flagged" data-testid="retired-tag">retired</span>}
              </td>
              <td className="actions">
                {r.revision === entry.pinned
                  ? <button type="button" data-testid="unpin" onClick={() => act(api.pin(entry.name, null))}>Unpin</button>
                  : <button type="button" data-testid="pin" disabled={r.retired} onClick={() => act(api.pin(entry.name, r.revision))}>Pin</button>}
                {!r.retired && <button type="button" data-testid="retire" onClick={() => act(api.retire(entry.name, r.revision))}>Retire</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
