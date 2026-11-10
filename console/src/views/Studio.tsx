// The Studio (plan C2): a procedure read and changed as cards. It opens on a revision, a draft, or a new
// empty procedure. Every change is a text edit at a span of procedure.aip (canvas/edit.ts), after which
// the console's process formats the text (`aip fmt --stdin`) and compiles it (`aip compile --partial`)
// against the bundle's files on this machine, and the canvas draws what the compiler made of it, with its
// diagnostics on the cards while a change is half done. Only a clean compile is saved: as a draft (the
// server holds the bundle with no revision), and "publish" gives that bundle the next revision. Unsaved
// edits are kept in this browser until they are saved or discarded.

import { useCallback, useEffect, useRef, useState } from "react";
import { describe, filesOf, graphOf, sourceOf } from "../api/client";
import { studioCheck, studioOpen, studioSave, type StudioCheck, type StudioSaved } from "../api/console";
import { Canvas, type Editing } from "../canvas/Canvas.tsx";
import { applyEdits, EditError, renameProcedure, setText, type TextEdit } from "../canvas/edit.ts";
import type { Graph } from "../canvas/model.ts";
import { Code } from "../highlight/Code.tsx";
import { bundleRef, href } from "../router";

/** What a new procedure starts as: the smallest program that compiles. */
export const NEW_PROCEDURE = `Procedure new_procedure "What this procedure does."

Start "What the procedure is given." {
  request: string "The request, as given."
  Next_Step end
}

End "What the procedure returns." {
  Read request
}
`;

interface Opened { workspace: string; original: string; files: Record<string, string>; scripts: string[] }
interface Kept { source: string; files: Record<string, string> }

const keyOf = (reference?: string) => `aip.studio:${reference ?? "new"}`;

function kept(reference?: string): Kept | null {
  try {
    const raw = localStorage.getItem(keyOf(reference));
    return raw ? (JSON.parse(raw) as Kept) : null;
  } catch { return null; }
}

export function Studio({ reference }: { reference?: string }) {
  const [opened, setOpened] = useState<Opened | null>(null);
  const [source, setSource] = useState("");
  const [changed, setChanged] = useState<Record<string, string>>({});
  const [check, setCheck] = useState<StudioCheck | null>(null);
  // The last graph the compiler could build: drawn, greyed, while the text does not parse.
  const [graph, setGraph] = useState<Graph | null>(null);
  const [undo, setUndo] = useState<string[]>([]);
  const [last, setLast] = useState<string>("");
  const [restored, setRestored] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<StudioSaved | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);
  const checking = useRef(0);

  const runCheck = useCallback(async (workspace: string, text: string, files: Record<string, string>) => {
    const ticket = ++checking.current;
    setBusy(true);
    try {
      const report = await studioCheck(workspace, text, files);
      if (ticket !== checking.current) return;
      setCheck(report);
      setSource(report.source);
      if (report.graph) setGraph(report.graph);
      setError(null);
    } catch (e) {
      if (ticket === checking.current) setError(describe(e));
    } finally {
      if (ticket === checking.current) setBusy(false);
    }
  }, []);

  // Open: the bundle's source and files (none for a new procedure) into a folder on this machine, then the first check.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        let original = NEW_PROCEDURE;
        let files: { path: string; text: string | null; base64: string | null; mode: number }[] = [];
        if (reference) {
          const bundle = await graphOf(reference);
          original = sourceOf(bundle);
          files = filesOf(bundle).map((f) => ({ path: f.path, text: f.text, base64: f.base64, mode: f.mode }));
        }
        const { workspace } = await studioOpen(files);
        if (!live) return;
        const texts = Object.fromEntries(files.filter((f) => f.text !== null).map((f) => [f.path, f.text as string]));
        const scripts = files.map((f) => f.path).filter((p) => p.startsWith("scripts/"));
        setOpened({ workspace, original, files: texts, scripts });
        const keep = kept(reference);
        const start = keep && (keep.source !== original || Object.keys(keep.files).length) ? keep : null;
        setRestored(start !== null);
        setChanged(start?.files ?? {});
        setSource(start?.source ?? original);
        await runCheck(workspace, start?.source ?? original, start?.files ?? {});
      } catch (e) {
        if (live) setError(describe(e));
      }
    })();
    return () => { live = false; };
  }, [reference, runCheck]);

  // Unsaved edits stay in this browser.
  useEffect(() => {
    if (!opened) return;
    if (source === opened.original && Object.keys(changed).length === 0) localStorage.removeItem(keyOf(reference));
    else if (source) localStorage.setItem(keyOf(reference), JSON.stringify({ source, files: changed }));
  }, [source, changed, opened, reference]);

  if (error && !opened) return <p className="error" role="alert">{error}</p>;
  if (!opened || check === null) return <p className="muted">Opening {reference ?? "a new procedure"} in the studio…</p>;

  const apply = (edits: TextEdit[], what: string) => {
    setUndo((u) => [...u, source]);
    setLast(what);
    setSaved(null);
    const next = applyEdits(source, edits);
    setSource(next);
    void runCheck(opened.workspace, next, changed);
  };
  const back = () => {
    const previous = undo.at(-1);
    if (previous === undefined) return;
    setUndo((u) => u.slice(0, -1));
    setLast("undo");
    setSaved(null);
    void runCheck(opened.workspace, previous, changed);
  };
  const discard = () => {
    localStorage.removeItem(keyOf(reference));
    setUndo([]);
    setChanged({});
    setRestored(false);
    setSaved(null);
    void runCheck(opened.workspace, opened.original, {});
  };
  const onFile = (path: string, text: string) => {
    const files = { ...changed, [path]: text };
    setChanged(files);
    setSaved(null);
    setLast(`prompt ${path}`);
    void runCheck(opened.workspace, source, files);
  };
  const save = async (publish: boolean) => {
    setBusy(true);
    try {
      const done = await studioSave(opened.workspace, source, changed, publish);
      setSaved(done);
      setError(null);
      if (publish) localStorage.removeItem(keyOf(reference));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  const parses = check.graph !== null;
  const errors = check.diagnostics.filter((d) => d.severity === "error");
  const editing: Editing | undefined = parses
    ? { onEdit: apply, scripts: opened.scripts, files: { ...opened.files, ...changed }, onFile }
    : undefined;
  const procedure = graph?.nodes.find((n) => n.labels.includes("Procedure"))?.properties;
  const name = typeof procedure?.name === "string" ? procedure.name : "";

  return (
    <article className="procedure studio" data-testid="studio">
      <nav className="crumbs">
        <a href={href({ page: "catalog" })}>catalog</a> / studio / {reference
          ? <a href={href({ page: "procedure", ref: reference })}><code>{reference}</code></a>
          : <span>a new procedure</span>}
      </nav>
      <h1>
        {name || "procedure.aip"} <span className="muted rev">studio</span>
      </h1>
      {parses && graph && (
        <Header graph={graph} source={source} onEdit={apply} />
      )}

      <div className="studio-bar">
        <span data-testid="studio-status" data-ok={check.ok ? "true" : "false"} className={check.ok ? "status-tag" : "status-tag flagged"}>
          {busy ? "compiling…" : check.ok ? "compiles" : !parses ? "does not parse" : `${errors.length} error${errors.length === 1 ? "" : "s"}`}
        </span>
        {last && <span className="muted small" data-testid="studio-last">last change: {last}</span>}
        <button type="button" onClick={back} disabled={undo.length === 0 || busy} data-testid="studio-undo">Undo</button>
        <button type="button" onClick={() => void save(false)} disabled={!check.ok || busy} data-testid="studio-save"
                title={check.ok ? "Hold it on the server as a draft: out of the catalog, its runs recorded as a draft's" : "Only what compiles is saved"}>
          Save draft
        </button>
        <button type="button" onClick={() => void save(true)} disabled={!check.ok || busy || !saved || saved.revision !== null} data-testid="studio-publish"
                title="Give the saved draft the next revision of its name">
          Publish
        </button>
        <label className="small"><input type="checkbox" data-testid="studio-view-source" checked={showSource} onChange={(e) => setShowSource(e.target.checked)} /> View source</label>
        {restored && (
          <span className="small muted" data-testid="studio-restored">
            These are edits you had not saved. <button type="button" onClick={discard}>Discard them</button>
          </span>
        )}
      </div>
      {saved && (
        <p className="small" data-testid="studio-saved" data-bundle={saved.bundle_id} data-revision={saved.revision ?? ""}>
          {saved.revision === null
            ? <>Saved as a draft of <code>{saved.name}</code>: <a href={href({ page: "procedure", ref: bundleRef(saved.bundle_id) })}>bundle <code>{saved.bundle_id.slice(0, 12)}</code></a>.
                {saved.draft ? " Publish gives it the next revision." : " That bundle is already published."}</>
            : <>Published <a href={href({ page: "procedure", ref: `${saved.name}@${saved.revision}` })}><code>{saved.name}@{saved.revision}</code></a>.</>}
        </p>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {!parses && (
        <p className="error" role="alert" data-testid="studio-unparsed">
          procedure.aip does not parse, so the cards show the last version that did and cannot be changed: undo, or discard the edits.
        </p>
      )}
      <Diagnostics check={check} />

      <div className={showSource ? "studio-split" : undefined}>
        {graph
          ? <Canvas graph={graph} source={source} direction="down" height="72vh" problems={check.diagnostics} editing={editing}
                    renderCode={(code, first) => <Code text={code} aip firstLine={first} />} />
          : <p className="muted">No graph yet.</p>}
        {showSource && (
          <section className="studio-source" data-testid="studio-source">
            <h2>procedure.aip</h2>
            <Code text={source} aip />
          </section>
        )}
      </div>
    </article>
  );
}

/** The procedure's name and description, changed in place. */
function Header({ graph, source, onEdit }: { graph: Graph; source: string; onEdit: (edits: TextEdit[], what: string) => void }) {
  const props = graph.nodes.find((n) => n.labels.includes("Procedure"))?.properties ?? {};
  const name = typeof props.name === "string" ? props.name : "";
  const description = typeof props.description === "string" ? props.description : "";
  const [n, setN] = useState(name);
  const [d, setD] = useState(description);
  const [problem, setProblem] = useState("");
  useEffect(() => setN(name), [name]);
  useEffect(() => setD(description), [description]);
  const run = (what: string, make: () => TextEdit[]) => {
    try { onEdit(make(), what); setProblem(""); } catch (e) { if (e instanceof EditError) setProblem(e.message); else throw e; }
  };
  return (
    <div className="studio-header" data-testid="studio-header">
      <label>name <input value={n} onChange={(e) => setN(e.target.value)} size={24} data-testid="studio-name" /></label>
      <button type="button" disabled={n === name} onClick={() => run("rename", () => renameProcedure(source, graph, n))}>Rename</button>
      <label className="grow">description <textarea value={d} rows={2} onChange={(e) => setD(e.target.value)} /></label>
      <button type="button" disabled={d === description} onClick={() => run("describe the procedure", () => setText(source, graph, "procedure", d))}>Change</button>
      {problem && <span className="error">{problem}</span>}
    </div>
  );
}

function Diagnostics({ check }: { check: StudioCheck }) {
  if (check.diagnostics.length === 0) return null;
  return (
    <ul className="issues" data-testid="studio-diagnostics">
      {check.diagnostics.map((d, i) => (
        <li key={i} data-severity={d.severity} data-code={d.code}>
          <code>{d.code}</code> {d.severity}{d.line !== null ? ` at line ${d.line}` : ""}{d.step ? ` (${d.step})` : ""}: {d.message}
        </li>
      ))}
    </ul>
  );
}
