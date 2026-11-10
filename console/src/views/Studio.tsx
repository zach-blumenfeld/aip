// The Studio (plan C4), for people who do not code: a chat that runs procedures, the graph beside it,
// and forms for field edits. It opens on a revision, a draft, or a new empty procedure, whose files the
// console's process keeps in a folder of its own (bin/aip-console.mjs, the Studio's workspaces).
//
// - The chat (StudioChat) runs build_procedure on the first brief of a new procedure and edit_procedure
//   after, with the agent model answering; the folder is what they write, and the page reads it again
//   when a run stops. Each run can be undone as a whole.
// - The graph is C3's step graph, control or data flow, drawn again after every run and every edit;
//   clicking a node opens its form (StudioForm). A form's change is a text edit at a span of
//   procedure.aip (studio/edit.ts), which the console's process formats (`aip fmt --stdin`) and compiles
//   (`aip compile --partial`) before the graph is drawn again; the compiler is the only rule book.
// - Source is a toggle, closed by default; Settings holds the agent model and the decision model.
// Only a clean compile is saved: as a draft (the server holds the bundle with no revision), and
// "publish" gives that bundle the next revision. Unsaved form edits are kept in this browser.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { describe, filesOf, graphOf, sourceOf } from "../api/client";
import {
  modelSettings, saveModelSettings, studioCheck, studioDocuments, studioOpen, studioRead, studioSave, studioUndo,
  type ModelSettings, type ModelSettingsChange, type StudioCheck, type StudioSaved,
} from "../api/console";
import type { Graph } from "../graph/bundle.ts";
import { dataEdges, dataKeys } from "../graph/dataflow.ts";
import { stepGraphOf } from "../graph/model.ts";
import { Code } from "../highlight/Code.tsx";
import { bundleRef, href } from "../router";
import { missingScripts, nameFromBrief } from "../studio/chat.ts";
import { applyEdits, EditError, renameProcedure, setText, type TextEdit } from "../studio/edit.ts";
import { DirectionToggle, StepGraph, useDirection } from "./StepGraph";
import { StudioChat, type ChatHost } from "./StudioChat";
import { StudioForm } from "./StudioForm";

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

interface Opened { workspace: string; original: string; files: Record<string, string> }
interface Kept { source: string; files: Record<string, string> }
/** What Undo takes back: a form's edit (the text before it), or a whole run of the chat (the launcher keeps the folder). */
type Step = { kind: "text"; source: string; what: string } | { kind: "run"; what: string };

const keyOf = (reference?: string) => `aip.studio:${reference ?? "new"}`;

function kept(reference?: string): Kept | null {
  try {
    const raw = localStorage.getItem(keyOf(reference));
    return raw ? (JSON.parse(raw) as Kept) : null;
  } catch { return null; }
}

/** The text files of `now` that differ from `then`. */
const differing = (now: Record<string, string>, then: Record<string, string>) =>
  Object.fromEntries(Object.entries(now).filter(([p, t]) => then[p] !== t));

export function Studio({ reference }: { reference?: string }) {
  const [opened, setOpened] = useState<Opened | null>(null);
  const [source, setSource] = useState("");
  /** The draft's text files as they are now; `changed` is what a form changed since the folder was last read. */
  const [files, setFiles] = useState<Record<string, string>>({});
  const [changed, setChanged] = useState<Record<string, string>>({});
  const [check, setCheck] = useState<StudioCheck | null>(null);
  // The last graph the compiler could build: drawn while the text does not parse.
  const [graph, setGraph] = useState<Graph | null>(null);
  const [undo, setUndo] = useState<Step[]>([]);
  const [last, setLast] = useState("");
  const [restored, setRestored] = useState(false);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [saved, setSaved] = useState<StudioSaved | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [flowMode, setFlowMode] = useState<"control" | "data">("control");
  const [direction, setDirection] = useDirection();
  const [documents, setDocuments] = useState<string[]>([]);
  const [built, setBuilt] = useState(false);
  const checking = useRef(0);
  const current = useRef({ source: "", files: {} as Record<string, string> });
  current.current = { source, files };

  const runCheck = useCallback(async (workspace: string, text: string, changedFiles: Record<string, string>) => {
    const ticket = ++checking.current;
    setBusy(true);
    try {
      const report = await studioCheck(workspace, text, changedFiles);
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

  useEffect(() => { modelSettings().then(setSettings).catch(() => setSettings(null)); }, []);

  // Open: the bundle's source and files (none for a new procedure) into a folder on this machine, then the first check.
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        let original = NEW_PROCEDURE;
        let name = "new_procedure";
        let bundleFiles: { path: string; text: string | null; base64: string | null; mode: number }[] = [];
        if (reference) {
          const bundle = await graphOf(reference);
          original = sourceOf(bundle);
          name = bundle.name;
          bundleFiles = filesOf(bundle).map((f) => ({ path: f.path, text: f.text, base64: f.base64, mode: f.mode }));
        }
        const { workspace } = await studioOpen(bundleFiles, name);
        if (!live) return;
        const texts = Object.fromEntries(bundleFiles.filter((f) => f.text !== null).map((f) => [f.path, f.text as string]));
        setOpened({ workspace, original, files: texts });
        const keep = kept(reference);
        const start = keep && (keep.source !== original || Object.keys(keep.files).length) ? keep : null;
        setRestored(start !== null);
        setFiles({ ...texts, ...(start?.files ?? {}) });
        setChanged(start?.files ?? {});
        setSource(start?.source ?? original);
        await runCheck(workspace, start?.source ?? original, start?.files ?? {});
      } catch (e) {
        if (live) setError(describe(e));
      }
    })();
    return () => { live = false; };
  }, [reference, runCheck]);

  // Unsaved edits stay in this browser: the source and the files that differ from what was opened.
  useEffect(() => {
    if (!opened) return;
    const files_ = differing(files, opened.files);
    if (source === opened.original && Object.keys(files_).length === 0) localStorage.removeItem(keyOf(reference));
    else if (source) localStorage.setItem(keyOf(reference), JSON.stringify({ source, files: files_ }));
  }, [source, files, opened, reference]);

  const model = useMemo(() => (graph ? stepGraphOf(graph) : null), [graph]);
  const flow = useMemo(() => (graph && flowMode === "data" ? dataEdges(dataKeys(graph)) : undefined), [graph, flowMode]);

  if (error && !opened) return <p className="error" role="alert">{error}</p>;
  if (!opened || check === null) return <p className="muted">Opening {reference ?? "a new procedure"} in the studio…</p>;

  /** The folder as a run or an undo left it. */
  const take = (read: Awaited<ReturnType<typeof studioRead>>) => {
    setCheck(read);
    setSource(read.source);
    if (read.graph) setGraph(read.graph);
    setFiles(read.files);
    setChanged({});
    setSaved(null);
  };

  const apply = (edits: TextEdit[], what: string) => {
    setUndo((u) => [...u, { kind: "text", source, what }]);
    setLast(what);
    setSaved(null);
    const next = applyEdits(source, edits);
    setSource(next);
    void runCheck(opened.workspace, next, changed);
  };
  const back = async () => {
    const step = undo.at(-1);
    if (!step) return;
    setUndo((u) => u.slice(0, -1));
    setLast(`undo ${step.what}`);
    setSaved(null);
    if (step.kind === "text") return void runCheck(opened.workspace, step.source, changed);
    setBusy(true);
    try { take(await studioUndo(opened.workspace)); } catch (e) { setError(describe(e)); } finally { setBusy(false); }
  };
  const discard = () => {
    localStorage.removeItem(keyOf(reference));
    setUndo([]);
    setChanged({});
    setFiles(opened.files);
    setRestored(false);
    setSaved(null);
    void runCheck(opened.workspace, opened.original, opened.files);
  };
  const onFile = (path: string, text: string) => {
    const next = { ...changed, [path]: text };
    setChanged(next);
    setFiles((f) => ({ ...f, [path]: text }));
    setSaved(null);
    setLast(`prompt ${path}`);
    void runCheck(opened.workspace, source, next);
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

  const isNew = !reference;
  const next: "build" | "edit" = isNew && !built ? "build" : "edit";
  const host: ChatHost = {
    start: (text) => {
      const kind = next;
      setUndo((u) => [...u, { kind: "run", what: kind === "build" ? "the build" : "the change" }]);
      setLast(kind === "build" ? "built by the chat" : "changed by the chat");
      setSaved(null);
      setSelected(null);
      const { source: s } = current.current;
      return kind === "build"
        ? { kind, call: { build: { workspace: opened.workspace, brief: text, name: nameFromBrief(text), source: s, files: changed } } }
        : { kind, call: { edit: { workspace: opened.workspace, instruction: text, source: s, files: changed } } };
    },
    before: () => current.current,
    built: () => setBuilt(true),
    settled: async () => {
      try {
        const read = await studioRead(opened.workspace);
        take(read);
        return { source: read.source, files: read.files };
      } catch (e) {
        setError(describe(e));
        return null;
      }
    },
    onDocuments: async (dropped) => {
      const docs = await Promise.all(dropped.map(async (f) => ({ name: f.name, base64: base64Of(new Uint8Array(await f.arrayBuffer())) })));
      const { documents: got } = await studioDocuments(opened.workspace, docs);
      setDocuments((d) => [...new Set([...d, ...got])]);
      return got;
    },
  };

  const parses = check.graph !== null;
  const errors = check.diagnostics.filter((d) => d.severity === "error");
  const scripts = missingScripts(check.diagnostics);
  const procedure = graph?.nodes.find((n) => n.labels.includes("Procedure"))?.properties;
  const name = typeof procedure?.name === "string" ? procedure.name : "";
  const notes: Record<string, string> = {};
  if (model) {
    for (const node of Object.values(model.nodes)) {
      const count = check.diagnostics.filter((d) => d.step === node.name && d.severity === "error").length;
      if (scripts.has(node.name)) notes[node.id] = "needs a script";
      else if (count) notes[node.id] = `${count} error${count === 1 ? "" : "s"}`;
    }
  }
  const blocked = busy || running;

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
      {parses && graph && <Header graph={graph} source={source} busy={blocked} onEdit={apply} />}

      <div className="studio-bar">
        <span data-testid="studio-status" data-ok={check.ok ? "true" : "false"} className={check.ok ? "status-tag" : "status-tag flagged"}>
          {running ? "the chat is working…" : busy ? "compiling…" : check.ok ? "compiles" : !parses ? "does not parse" : `${errors.length} error${errors.length === 1 ? "" : "s"}`}
        </span>
        {last && <span className="muted small" data-testid="studio-last">last change: {last}</span>}
        <button type="button" onClick={() => void back()} disabled={undo.length === 0 || blocked} data-testid="studio-undo"
                title={undo.length ? `Undo ${undo.at(-1)!.what}` : "Nothing to undo"}>Undo</button>
        <button type="button" onClick={() => void save(false)} disabled={!check.ok || blocked} data-testid="studio-save"
                title={check.ok ? "Hold it on the server as a draft: out of the catalog, its runs recorded as a draft's" : "Only what compiles is saved"}>
          Save draft
        </button>
        <button type="button" onClick={() => void save(true)} disabled={!check.ok || blocked || !saved || saved.revision !== null} data-testid="studio-publish"
                title="Give the saved draft the next revision of its name">
          Publish
        </button>
        <label className="small"><input type="checkbox" data-testid="studio-view-source" checked={showSource} onChange={(e) => setShowSource(e.target.checked)} /> Source</label>
        <label className="small"><input type="checkbox" data-testid="studio-view-settings" checked={showSettings} onChange={(e) => setShowSettings(e.target.checked)} /> Settings</label>
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
      {showSettings && <Settings settings={settings} onSaved={setSettings} />}
      {!parses && (
        <p className="error" role="alert" data-testid="studio-unparsed">
          procedure.aip does not parse, so the graph shows the last version that did and its forms are closed: undo, or ask the chat to fix it.
        </p>
      )}
      {scripts.size > 0 && (
        <p className="boundary" data-testid="studio-needs-scripts">
          {[...scripts].map(([step, path]) => `${step} needs ${path}`).join("; ")}: a script is code, so ask a developer to write it.
          Until it is there the procedure does not compile and cannot be saved.
        </p>
      )}

      <div className="studio-grid">
        <StudioChat host={host} next={next} settings={settings} documents={documents} busy={blocked} setBusy={setRunning} />
        <section className="studio-graph" data-testid="studio-graph">
          <div className="graph-controls">
            <div className="flow-toggle" role="radiogroup" aria-label="graph">
              {(["control", "data"] as const).map((m) => (
                <label key={m}><input type="radio" name="studio-flow" checked={flowMode === m} onChange={() => setFlowMode(m)} /> {m} flow</label>
              ))}
            </div>
            <DirectionToggle direction={direction} onChange={setDirection} />
          </div>
          <p className="muted small">Click a step or a loop to change it. A new step, a loop or a rewire is the chat&apos;s to make.</p>
          {model ? (
            <div className="graph-scroll">
              <StepGraph graph={model} direction={direction} flow={flow} selected={selected} notes={notes}
                         onSelect={(id) => setSelected((s) => (s === id ? null : id))} />
            </div>
          ) : <p className="muted">No graph yet.</p>}
          {selected && graph && parses && (
            <StudioForm graph={graph} source={source} id={selected} files={files} diagnostics={check.diagnostics} busy={blocked}
                        missingScript={(() => { const n = model?.nodes[selected]?.name; return n ? scripts.get(n) ?? null : null; })()}
                        onEdit={apply} onFile={onFile} onClose={() => setSelected(null)} />
          )}
        </section>
      </div>

      <Diagnostics check={check} />
      {showSource && (
        <section className="studio-source" data-testid="studio-source">
          <h2>procedure.aip</h2>
          <Code text={source} aip />
        </section>
      )}
    </article>
  );
}

function base64Of(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

/** The procedure's name and description, changed in place. */
function Header({ graph, source, busy, onEdit }: { graph: Graph; source: string; busy: boolean; onEdit: (edits: TextEdit[], what: string) => void }) {
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
      <button type="button" disabled={busy || n === name} onClick={() => run("rename", () => renameProcedure(source, graph, n))}>Rename</button>
      <label className="grow">description <textarea value={d} rows={2} onChange={(e) => setD(e.target.value)} /></label>
      <button type="button" disabled={busy || d === description} onClick={() => run("describe the procedure", () => setText(source, graph, "procedure", d))}>Change</button>
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

/** Where to get an agent model's endpoint, one line per provider; any Chat Completions endpoint works. */
const PROVIDERS = [
  ["Anthropic (the default)", "https://api.anthropic.com/v1", "claude-opus-5-5"],
  ["OpenAI", "https://api.openai.com/v1", "a model name from your account"],
  ["Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "a Gemini model name"],
  ["Ollama, on this machine", "http://localhost:11434/v1", "a model you have pulled"],
];

/** The agent model and the decision model, written through the launcher to `aip config`. A key is never shown: a field
 *  left empty keeps the one set. */
function Settings({ settings, onSaved }: { settings: ModelSettings | null; onSaved: (s: ModelSettings) => void }) {
  const [form, setForm] = useState<ModelSettingsChange>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const set = (k: keyof ModelSettingsChange, v: string) => { setForm((f) => ({ ...f, [k]: v })); setDone(false); };
  const fromEnv = (s: { source: string } | null | undefined) => !!s && /^AIP_/.test(s.source);
  const go = async () => {
    const change = Object.fromEntries(Object.entries(form).filter(([, v]) => v !== undefined && v !== "")) as ModelSettingsChange;
    try { onSaved(await saveModelSettings(change)); setForm({}); setProblem(null); setDone(true); } catch (e) { setProblem(describe(e)); }
  };
  return (
    <section className="studio-settings" data-testid="studio-settings">
      <h2>Settings</h2>
      <fieldset>
        <legend>agent model <span className="muted small">writes and changes procedures in the chat</span></legend>
        <p className="small muted" data-testid="settings-agent">
          {settings?.agent ? <>now: <code>{settings.agent.endpoint}</code>, <code>{settings.agent.model}</code>, key {settings.agent.key ? "set" : "not set"}</> : "none set"}
          {fromEnv(settings?.agent) && <> — set by the environment ({settings!.agent!.source}), which wins over what is saved here</>}
        </p>
        <label className="form-row">endpoint <input type="url" placeholder={settings?.agent?.endpoint ?? PROVIDERS[0][1]} value={form.agent_model ?? ""} onChange={(e) => set("agent_model", e.target.value)} /></label>
        <label className="form-row">model <input type="text" placeholder={settings?.agent?.model ?? PROVIDERS[0][2]} value={form.agent_model_name ?? ""} onChange={(e) => set("agent_model_name", e.target.value)} /></label>
        <label className="form-row">key <input type="password" autoComplete="off" placeholder={settings?.agent?.key ? "set; type to replace it" : "the provider's API key"} value={form.agent_model_key ?? ""} onChange={(e) => set("agent_model_key", e.target.value)} data-testid="settings-agent-key" /></label>
        <ul className="small muted">
          {PROVIDERS.map(([who, url, model]) => <li key={who}>{who}: <code>{url}</code>, {model}</li>)}
        </ul>
      </fieldset>
      <fieldset>
        <legend>decision model <span className="muted small">answers the procedures&apos; Decide steps</span></legend>
        <p className="small muted" data-testid="settings-decision">
          {settings?.decision ? <>now: <code>{settings.decision.endpoint}</code>, key {settings.decision.key ? "set" : "not set"}</> : "none set"}
          {fromEnv(settings?.decision) && <> — set by the environment ({settings!.decision!.source})</>}
        </p>
        <label className="form-row">endpoint <input type="url" placeholder="https://api.typesafe.ai (TypeSafe's, the default)" value={form.decision_model ?? ""} onChange={(e) => set("decision_model", e.target.value)} /></label>
        <label className="form-row">key <input type="password" autoComplete="off" placeholder={settings?.decision?.key ? "set; type to replace it" : "the decision model's API key"} value={form.decision_model_key ?? ""} onChange={(e) => set("decision_model_key", e.target.value)} /></label>
      </fieldset>
      <div className="actions">
        <button type="button" onClick={() => void go()} disabled={Object.values(form).every((v) => !v)} data-testid="settings-save">Save settings</button>
        {done && <span className="small" data-testid="settings-saved">saved to aip config</span>}
      </div>
      {problem && <p className="error" role="alert">{problem}</p>}
    </section>
  );
}
