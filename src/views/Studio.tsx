import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { DirectionToggle, StepGraph, useDirection } from "./StepGraph";
import { CONFIDENCE_TYPE, DATA_TYPES, confidenceKey, emptyDraft, FORMAT_VERSION, QUESTION_TYPES, RUNNABLE_KINDS, startOf, type Draft, type IOItem, type Question, type Step, type StepKind } from "../studio/draft";
import { KINDS, addStepAfter, addStepOnBranch, declareOutput, declareStartInput, deleteStep, flowOf, graphOf, label, possibleValues, prefillBranches, renameStep, setStart } from "../studio/edit";
import { carried, importSkill, versionMessage } from "../studio/import";
import { availableKeys, lint, type AvailableKey, type Issue, type Tier } from "../studio/lint";
import { autofix } from "../studio/fixes";
import { fileTexts } from "../studio/scaffold";
import { addDraft, deleteDraft, loadDraft, openShelf, renameDraft, saveDraft, storageAvailable, switchTo, type Shelf } from "../studio/storage";
import { ExportPanel } from "./StudioExport";
import { AgentPanel } from "./StudioAgent";
import { DraftsBar } from "./StudioDrafts";
import { revisionFiles } from "./Zip";
import { describe } from "./Source";
import type { ZipFile } from "../zip";

const STEP_NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const TIERS: Tier[] = ["error", "unfinished", "warning", "info"];
/** How many Draft snapshots undo keeps, and how close together keystrokes in one text field fold into one step. */
const HISTORY = 100;
const COALESCE_MS = 800;

const typingIn = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
const isText = (t: Element | null) => t instanceof HTMLTextAreaElement || (t instanceof HTMLInputElement && t.type === "text");

/** The Studio: the step graph of a Draft on the left, a side panel for the selected step (or the procedure) on
 *  the right, and the linter's verdict under the graph. Every edit is autosaved to localStorage, one key per draft.
 *  `importRef` opens a catalog revision as a new draft, `fresh` a blank one. */
export function Studio({ importRef, fresh }: { importRef?: string; fresh?: boolean }) {
  const [initial] = useState(openShelf);
  const [shelf, setShelf] = useState<Shelf>(initial.shelf);
  const [draft, setDraft] = useState<Draft>(initial.draft);
  const [storageOk] = useState(storageAvailable);
  const [notice, setNotice] = useState<{ error: boolean; text: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [direction, setDirection] = useDirection();
  const [showFlow, setShowFlow] = useState(false);
  const [saved, setSaved] = useState<"saved" | "unsaved" | "no-storage">(storageOk ? "saved" : "no-storage");
  const [focus, setFocus] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [agent, setAgent] = useState(false);
  const latest = useRef(draft);
  const currentId = useRef(shelf.current);
  const shelfRef = useRef(shelf);
  shelfRef.current = shelf;
  const dirty = useRef(false);

  // Undo and redo: a bounded list of Draft snapshots. Keystrokes in one text field close together are one step.
  const cur = useRef(draft);
  cur.current = draft;
  const past = useRef<Draft[]>([]);
  const future = useRef<Draft[]>([]);
  const lastTyped = useRef<{ at: number; el: Element | null }>({ at: 0, el: null });
  const commit = (next: Draft) => {
    const el = document.activeElement;
    const now = Date.now();
    const fold = isText(el) && lastTyped.current.el === el && now - lastTyped.current.at < COALESCE_MS;
    if (!fold) {
      past.current.push(cur.current);
      if (past.current.length > HISTORY) past.current.shift();
    }
    lastTyped.current = isText(el) ? { at: now, el } : { at: 0, el: null };
    future.current = [];
    cur.current = next;
    setDraft(next);
  };
  const travel = (from: { current: Draft[] }, to: { current: Draft[] }) => {
    const d = from.current.pop();
    if (!d) return;
    to.current.push(cur.current);
    lastTyped.current = { at: 0, el: null };
    cur.current = d;
    setDraft(d);
  };
  const undo = () => travel(past, future);
  const redo = () => travel(future, past);

  const edit = (change: (d: Draft) => void) => {
    const c = structuredClone(cur.current);
    change(c);
    commit(c);
  };

  // Autosave, debounced; and once more as the page goes away, so a reload right after an edit keeps it.
  const flush = () => {
    if (!dirty.current) return;
    dirty.current = false;
    setSaved(saveDraft(currentId.current, latest.current) ? "saved" : "no-storage");
  };
  useEffect(() => {
    if (latest.current === draft) return;
    latest.current = draft;
    dirty.current = true;
    setSaved((s) => (s === "no-storage" ? s : "unsaved"));
    const t = setTimeout(flush, 300);
    return () => clearTimeout(t);
  }, [draft]);
  useEffect(() => {
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, []);

  /** Show another draft: the open one is saved first, and the new one is not marked as changed. */
  const show = (next: Shelf, d: Draft) => {
    flush();
    currentId.current = next.current;
    latest.current = d;
    cur.current = d;
    past.current = [];
    future.current = [];
    setShelf(next);
    setDraft(d);
    setSelected(null);
    setExporting(false);
    setAgent(false);
  };
  const open = (d: Draft, name: string) => { flush(); show(addDraft(shelfRef.current, d, name), d); };

  // A link from elsewhere (a procedure page, the catalog) opens a new draft once, then the hash goes back to #/studio
  // so a reload does not open another.
  const handled = useRef<string | null>(null);
  useEffect(() => {
    const key = importRef ? `import:${importRef}` : fresh ? "new" : null;
    if (!key || handled.current === key) return;
    handled.current = key;
    history.replaceState(null, "", "#/studio");
    if (fresh) { open(emptyDraft(), "untitled draft"); setNotice(null); return; }
    importFrom(importRef!);
  }, [importRef, fresh]);

  function importFrom(ref: string) {
    setNotice({ error: false, text: `importing ${ref}…` });
    revisionFiles(ref).then(
      (files) => importFiles(files, ref),
      (e) => setNotice({ error: true, text: `Could not import ${ref}: ${describe(e)}` }),
    );
  }
  function importFiles(files: ZipFile[], from: string) {
    try {
      open(importSkill(files), from);
      setNotice({ error: false, text: `Imported ${from} as a new draft.` });
    } catch (e) {
      setNotice({ error: true, text: `Could not import ${from}: ${describe(e)}` });
    }
  }

  const files = useMemo(() => carried(draft), [draft.files]);
  // In the panel's order, by tier, so F8 walks them as they are listed.
  const issues = useMemo(() => {
    const all = lint(draft, { files: fileTexts(draft, files) });
    return TIERS.flatMap((t) => all.filter((i) => i.tier === t));
  }, [draft, files]);
  const marks = useMemo(() => {
    const m = new Map<string, Tier>();
    for (const i of issues) {
      if (!i.stepId) continue;
      const have = m.get(i.stepId);
      if (!have || TIERS.indexOf(i.tier) < TIERS.indexOf(have)) m.set(i.stepId, i.tier);
    }
    return m;
  }, [issues]);
  const g = useMemo(() => graphOf(draft), [draft]);
  const available = useMemo(() => availableKeys(draft), [draft]);
  const flow = useMemo(() => (showFlow ? flowOf(draft) : undefined), [showFlow, draft]);
  const step = draft.steps.find((s) => s.id === selected);
  const select = (id: string | null, field?: string) => { setSelected(id); setFocus(field ?? null); };
  const [current, setCurrent] = useState<number | null>(null);
  const pick = (i: Issue) => { setCurrent(issues.indexOf(i)); select(i.stepId ?? null, i.field); };
  const removeStep = (id: string) => { commit(deleteStep(cur.current, id)); setSelected(null); };

  // Keyboard: F8 and Shift+F8 walk the issues (from anywhere, like an editor's problem list); outside a form field,
  // Delete removes the selected step and Cmd/Ctrl+Z undoes, Shift+Cmd/Ctrl+Z or Ctrl+Y redoes.
  const keys = useRef({ issues, current, selected, pick, removeStep, undo, redo });
  keys.current = { issues, current, selected, pick, removeStep, undo, redo };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = keys.current;
      if (e.key === "F8") {
        if (!k.issues.length) return;
        e.preventDefault();
        const n = k.issues.length;
        const at = k.current === null || k.current >= n ? (e.shiftKey ? n - 1 : 0) : (k.current + (e.shiftKey ? n - 1 : 1)) % n;
        k.pick(k.issues[at]);
        return;
      }
      if (typingIn(e.target)) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) k.redo(); else k.undo(); return; }
      if (e.ctrlKey && e.key.toLowerCase() === "y") { e.preventDefault(); k.redo(); return; }
      if (e.key === "Delete" && k.selected) { e.preventDefault(); k.removeStep(k.selected); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Move focus to the field a lint issue names, once the panel it lives in has rendered.
  useEffect(() => {
    if (!focus) return;
    const top = focus.split(/[.[]/)[0];
    document.querySelector<HTMLElement>(`.studio-panel [data-field="${focus}"], .studio-panel [data-field="${top}"]`)?.focus();
    setFocus(null);
  }, [focus, selected]);

  const add = (after: string | undefined, kind: StepKind) => {
    const r = addStepAfter(draft, after, kind);
    commit(r.draft);
    setSelected(r.id);
  };
  const addOnBranch = (router: string, index: number, kind: StepKind) => {
    const r = addStepOnBranch(draft, router, index, kind);
    commit(r.draft);
    setSelected(r.id);
  };

  return (
    <div className="studio" data-testid="studio">
      <h1>Studio</h1>
      <p className="muted">
        Build a procedure step by step. Each edit is checked as you make it and kept in this browser
        {" "}<span data-testid="studio-saved" data-state={saved}>
          ({saved === "saved" ? "saved" : saved === "unsaved" ? "saving…" : "this browser will not keep it: storage is unavailable"})
        </span>.
      </p>
      {!storageOk && (
        <p className="error" role="alert" data-testid="storage-notice">
          This browser does not let the page keep anything, so drafts last only until the page is closed or reloaded. Export the scaffold to keep your work.
        </p>
      )}
      <DraftsBar shelf={shelf}
        onSwitch={(id) => { flush(); const d = loadDraft(id); if (d) show(switchTo(shelf, id), d); }}
        onNew={() => open(emptyDraft(), "untitled draft")}
        onRename={(label) => setShelf(renameDraft(shelf, shelf.current, label))}
        onDelete={() => { const r = deleteDraft(shelf, shelf.current); dirty.current = false; show(r.shelf, r.draft); }}
        onReset={() => commit(emptyDraft())}
        onImport={importFiles}
        onImportError={(text) => setNotice({ error: true, text })}
        onImportRef={importFrom} />
      {notice && <p className={notice.error ? "error" : "muted"} role={notice.error ? "alert" : "status"} data-testid="studio-notice">{notice.text}</p>}
      {versionMessage(draft.aipVersion) && (
        <div className="published-note" data-testid="version-banner">
          <p>This skill is written in format <code>{draft.aipVersion}</code>; the Studio edits format <code>{FORMAT_VERSION}</code>. aip-spec says:</p>
          <p className="muted">{versionMessage(draft.aipVersion)}</p>
          <p>The export stamps <code>{FORMAT_VERSION}</code> and writes the {FORMAT_VERSION} runtime block.</p>
        </div>
      )}
      <div className="studio-grid">
        <section>
          <div className="studio-bar">
            <DirectionToggle direction={direction} onChange={setDirection} />
            <label className="direction-toggle">
              <input type="checkbox" checked={showFlow} onChange={(e) => setShowFlow(e.target.checked)} /> data flow
            </label>
            <button onClick={() => select(null)}>procedure settings</button>
            <button onClick={() => setExporting((x) => !x)} aria-expanded={exporting} data-testid="studio-export">Export scaffold…</button>
            <button onClick={() => setAgent((x) => !x)} aria-expanded={agent} data-testid="studio-agent">Complete with an agent…</button>
            <button onClick={undo} disabled={!past.current.length} data-testid="studio-undo" title="Cmd/Ctrl+Z">undo</button>
            <button onClick={redo} disabled={!future.current.length} data-testid="studio-redo" title="Shift+Cmd/Ctrl+Z">redo</button>
          </div>
          <p className="muted small">F8 and Shift+F8: next and previous issue. Outside a field: Delete removes the selected step, Cmd/Ctrl+Z undoes, Shift+Cmd/Ctrl+Z redoes.</p>
          {exporting && <ExportPanel draft={draft} files={files} onClose={() => setExporting(false)} />}
          {agent && (
            <AgentPanel draft={draft} files={files} issues={issues} onClose={() => setAgent(false)}
              onPick={(r) => select(r.stepId ?? null, r.field)}
              onChange={edit}
              onAccept={commit} />
          )}
          {draft.steps.length === 0 ? (
            <div className="studio-panel" data-testid="studio-empty">
              <h2>Start with the first step</h2>
              <p className="muted">
                A procedure begins at its <code>start</code> step, which holds the inputs the client supplies and names the
                first step that runs. Pick that step's kind: the start step is added with it.
              </p>
              <AddKinds label="Add the first step" kinds={RUNNABLE_KINDS} onAdd={(k) => add(undefined, k)} />
            </div>
          ) : (
            <StepGraph steps={g.steps} edges={g.edges} branches={g.branches} start={g.start} end={g.end}
              direction={direction} flow={flow} onSelect={(id) => select(id)} selected={selected ?? undefined} labels={g.labels} marks={marks} />
          )}
          <LintPanel issues={issues} draft={draft} current={current} onPick={pick} onFix={commit} />
        </section>
        <aside className="studio-panel" data-testid="studio-panel">
          {step
            ? <StepPanel key={step.id} draft={draft} step={step} edit={edit} available={available.get(step.id) ?? []}
                onAdd={(k) => add(step.id, k)}
                onDelete={() => removeStep(step.id)}
                onStart={() => commit(setStart(draft, step.id))}
                onPrefill={() => commit(prefillBranches(draft, step.id))}
                onAddOnBranch={(i, k) => addOnBranch(step.id, i, k)} />
            : <ProcedurePanel draft={draft} edit={edit} />}
        </aside>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------------------------- lint panel

function LintPanel({ issues, draft, current, onPick, onFix }: {
  issues: Issue[]; draft: Draft; current: number | null; onPick: (i: Issue) => void; onFix: (d: Draft) => void;
}) {
  const where = (i: Issue) => {
    const s = draft.steps.find((x) => x.id === i.stepId);
    return s ? `${label(s)}: ` : "";
  };
  return (
    <section className="studio-lint" data-testid="lint-panel" aria-label="lint">
      <h2>Lint</h2>
      {issues.length === 0 && <p className="muted" data-testid="lint-clean">No issues.</p>}
      {TIERS.map((tier) => {
        const these = issues.filter((i) => i.tier === tier);
        if (!these.length) return null;
        return (
          <div key={tier} className={`tier-${tier}`} data-testid={`lint-${tier}`}>
            <h3>{tier} ({these.length})</h3>
            <ul>
              {these.map((i, n) => {
                const fix = autofix(i, draft);
                return (
                  <li key={n} data-code={i.code} data-step={i.stepId} aria-current={issues.indexOf(i) === current || undefined}>
                    <button className="linkish" onClick={() => onPick(i)}>{where(i)}{i.message}</button> <code className="muted">{i.code}</code>
                    {i.code === "unproduced_input" && i.key !== undefined && <Fixes issue={i} draft={draft} onFix={onFix} />}
                    {fix && <>{" "}<button data-testid="lint-autofix" onClick={() => onFix(fix.apply(draft))}>{fix.label}</button></>}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

/** The one-click ways to give an unproduced key a producer: the client supplies it, or an earlier step outputs it. */
function Fixes({ issue, draft, onFix }: { issue: Issue; draft: Draft; onFix: (d: Draft) => void }) {
  const key = issue.key!;
  const consumer = draft.steps.find((s) => s.id === issue.stepId);
  const type = consumer?.inputs.find((i) => i.name === key)?.type ?? "string";
  const makers = draft.steps.filter((s) => (s.kind === "execution" || s.kind === "client_task") && s.id !== issue.stepId);
  return (
    <span className="fixes" data-testid="lint-fixes">
      {" "}
      {startOf(draft.steps) && (
        <button aria-label={`declare ${key} as a start input`} onClick={() => onFix(declareStartInput(draft, key, type))}>declare as start input</button>
      )}
      {makers.length > 0 && (
        <select aria-label={`make ${key} an output of`} value="" onChange={(e) => e.target.value && onFix(declareOutput(draft, e.target.value, key, type))}>
          <option value="">make it an output of…</option>
          {makers.map((m) => <option key={m.id} value={m.id}>{label(m)}</option>)}
        </select>
      )}
    </span>
  );
}

// ----------------------------------------------------------------------------------------------- form bits

function Field({ name, children, hint }: { name: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="field">
      <span>{name}</span>
      {children}
      {hint && <span className="hint muted">{hint}</span>}
    </label>
  );
}

function Text({ name, value, onChange, field, area, invalid, hint, placeholder }: {
  name: string; value: string; onChange: (v: string) => void; field?: string; area?: boolean; invalid?: boolean; hint?: ReactNode; placeholder?: string;
}) {
  return (
    <Field name={name} hint={hint}>
      {area
        ? <textarea value={value} data-field={field} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
        : <input type="text" value={value} data-field={field} placeholder={placeholder} aria-invalid={invalid || undefined} onChange={(e) => onChange(e.target.value)} />}
    </Field>
  );
}

/** A list of strings: one text input per entry, with add and remove. */
function Strings({ name, items, onChange, field, area }: { name: string; items: string[]; onChange: (v: string[]) => void; field: string; area?: boolean }) {
  return (
    <fieldset>
      <legend>{name}</legend>
      {items.map((v, i) => (
        <div className="row" key={i}>
          {area
            ? <textarea value={v} data-field={i === 0 ? field : undefined} aria-label={`${name} ${i + 1}`} onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))} />
            : <input type="text" value={v} data-field={i === 0 ? field : undefined} aria-label={`${name} ${i + 1}`} onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))} />}
          <button onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label={`remove ${name} ${i + 1}`}>remove</button>
        </div>
      ))}
      <button onClick={() => onChange([...items, ""])}>add</button>
    </fieldset>
  );
}

function AddKinds({ label: text, kinds, onAdd }: { label: string; kinds: readonly StepKind[]; onAdd: (k: StepKind) => void }) {
  return (
    <div className="add-kinds" role="group" aria-label={text}>
      {kinds.map((k) => <button key={k} onClick={() => onAdd(k)}>+ {k}</button>)}
    </div>
  );
}

// ----------------------------------------------------------------------------------------------- procedure panel

function ProcedurePanel({ draft, edit }: { draft: Draft; edit: (c: (d: Draft) => void) => void }) {
  const r = draft.requires;
  return (
    <div data-testid="procedure-panel">
      <h2>Procedure</h2>
      <Text name="name" field="name" value={draft.name} onChange={(v) => edit((d) => { d.name = v; })}
        hint="lowercase letters, digits and hyphens" />
      <Text name="description" field="description" area value={draft.description} onChange={(v) => edit((d) => { d.description = v; })} />
      <Text name="purpose" field="purpose" area value={draft.purpose} onChange={(v) => edit((d) => { d.purpose = v; })} />
      <Strings name="trigger_when" field="triggerWhen" items={draft.triggerWhen} onChange={(v) => edit((d) => { d.triggerWhen = v; })} />
      <Strings name="do_not_use_when" field="doNotUseWhen" items={draft.doNotUseWhen} onChange={(v) => edit((d) => { d.doNotUseWhen = v; })} />
      <Strings name="anti_patterns" field="antiPatterns" items={draft.antiPatterns} onChange={(v) => edit((d) => { d.antiPatterns = v; })} />
      <fieldset>
        <legend>requires</legend>
        <label className="option">
          <input type="checkbox" checked={!!r} data-field="requires"
            onChange={(e) => edit((d) => { d.requires = e.target.checked ? { interpreter: { name: "python", version: "3.10" }, packages: [], tools: [] } : undefined; })} /> scripts need an interpreter
        </label>
        {r && (
          <>
            <Text name="interpreter" field="requires.interpreter.name" value={r.interpreter.name}
              onChange={(v) => edit((d) => { d.requires!.interpreter.name = v; })} />
            <Text name="version" field="requires.interpreter.version" value={r.interpreter.version ?? ""}
              onChange={(v) => edit((d) => { d.requires!.interpreter.version = v || undefined; })} />
            <Strings name="packages" field="requires.packages" items={r.packages} onChange={(v) => edit((d) => { d.requires!.packages = v; })} />
            <Strings name="tools" field="requires.tools" items={r.tools} onChange={(v) => edit((d) => { d.requires!.tools = v; })} />
          </>
        )}
      </fieldset>
    </div>
  );
}

// ----------------------------------------------------------------------------------------------- step panel

interface StepPanelProps {
  draft: Draft;
  step: Step;
  /** The keys this step may take as inputs. */
  available: AvailableKey[];
  edit: (c: (d: Draft) => void) => void;
  onAdd: (k: StepKind) => void;
  onDelete: () => void;
  onStart: () => void;
  onPrefill: () => void;
  onAddOnBranch: (index: number, kind: StepKind) => void;
}

function StepPanel({ draft, step, available, edit, onAdd, onDelete, onStart, onPrefill, onAddOnBranch }: StepPanelProps) {
  const at = (d: Draft) => d.steps.find((s) => s.id === step.id)!;
  const set = (change: (s: Step) => void) => edit((d) => change(at(d)));
  const others = draft.steps.filter((s) => s.id !== step.id && s.kind !== "start");
  const start = startOf(draft.steps);
  const isStart = step.kind === "start";
  const isFirst = start?.next === step.id;
  const runnable = RUNNABLE_KINDS.includes(step.kind);
  const target = (value: string | undefined, onChange: (v: string | undefined) => void, field?: string, aria?: string, from: Step[] = others) => (
    <select value={value ?? ""} data-field={field} aria-label={aria} onChange={(e) => onChange(e.target.value || undefined)}>
      <option value="">(none)</option>
      {from.map((s) => <option key={s.id} value={s.id}>{label(s)}</option>)}
      {value && !from.some((s) => s.id === value) && <option value={value}>{draft.steps.find((s) => s.id === value)?.name || value} (not a step here)</option>}
    </select>
  );

  return (
    <div data-testid="step-panel" data-step={step.id}>
      <h2>{label(step)} <span className="kind-tag" style={{ ["--kind" as string]: `var(--${step.kind})` }}>{step.kind}</span></h2>
      {step.kind !== "end" && step.kind !== "router" && (
        <>
          <strong className="small">Add a step after this one</strong>
          <AddKinds label={`Add step after ${label(step)}`} kinds={KINDS} onAdd={onAdd} />
        </>
      )}
      <Text name="name" field="name" value={step.name} invalid={!STEP_NAME.test(step.name)} onChange={(v) => set((s) => renameStep(s, v))}
        hint={STEP_NAME.test(step.name) ? "lowercase letters, digits and hyphens" : <span className="error">use lowercase letters, digits and single hyphens</span>} />
      <Text name="description" field="description" area value={step.description} onChange={(v) => set((s) => { s.description = v; })} />

      {isStart && (
        <>
          <p className="muted small">The procedure begins here: the client supplies these inputs, and the run goes to the first step.</p>
          <Field name="first step (inputs_to)" hint="the first step that runs, with the inputs as its state">
            {target(step.next, (v) => set((s) => { s.next = v; }), "next", "first step", others.filter((s) => RUNNABLE_KINDS.includes(s.kind)))}
          </Field>
        </>
      )}
      {runnable && (
        <Field name="next step (inputs_to)">
          {target(step.next, (v) => set((s) => { s.next = v; }), "next", "next step")}
        </Field>
      )}

      {step.kind === "router" && <RouterFields draft={draft} step={step} available={available} set={set} target={target} onPrefill={onPrefill} onAddOnBranch={onAddOnBranch} />}
      {step.kind === "decision" && <DecisionFields step={step} set={set} />}
      {step.kind === "execution" && (
        <>
          <Text name="script" field="script" value={step.script ?? ""} onChange={(v) => set((s) => { s.script = v; })} hint="under scripts/; the export writes a Python stub here" />
          <Field name="command" hint="Python only for now">
            <select value={step.command?.join(" ") ?? ""} data-field="command" onChange={(e) => set((s) => { s.command = e.target.value ? [e.target.value] : undefined; })}>
              <option value="">default (python)</option>
              <option value="python">python</option>
              {step.command && step.command.join(" ") !== "python" && <option value={step.command.join(" ")}>{step.command.join(" ")} (not Python)</option>}
            </select>
          </Field>
          <Strings name="assets" field="assets" items={step.assets ?? []} onChange={(v) => set((s) => { s.assets = v; })} />
          <Field name="timeout (seconds)">
            <NumberInput value={step.timeout} field="timeout" ariaLabel="timeout" onCommit={(n) => set((s) => { s.timeout = n; })} />
          </Field>
        </>
      )}
      {step.kind === "client_task" && (
        <>
          <Text name="template" field="template" value={step.template ?? ""} onChange={(v) => set((s) => { s.template = v; })} hint="under assets/; the export writes a placeholder template here" />
          <Strings name="assets" field="assets" items={step.assets ?? []} onChange={(v) => set((s) => { s.assets = v; })} />
          <fieldset>
            <legend>references</legend>
            {(step.references ?? []).map((r, i) => (
              <div className="row" key={i}>
                <input type="text" value={r.path} data-field={`references[${i}].path`} aria-label={`reference ${i + 1} path`} placeholder="references/…" onChange={(e) => set((s) => { s.references![i].path = e.target.value; })} />
                <input type="text" value={r.description} aria-label={`reference ${i + 1} description`} placeholder="description" onChange={(e) => set((s) => { s.references![i].description = e.target.value; })} />
                <button onClick={() => set((s) => { s.references!.splice(i, 1); })}>remove</button>
              </div>
            ))}
            <button onClick={() => set((s) => { (s.references ??= []).push({ path: "references/", description: "" }); })}>add</button>
          </fieldset>
          <label className="option">
            <input type="checkbox" checked={step.framing !== false} onChange={(e) => set((s) => { s.framing = e.target.checked ? undefined : false; })} /> framing
          </label>
        </>
      )}

      {step.kind !== "router" && (
        <IOEditor which="inputs" items={step.inputs} onChange={(v) => set((x) => { x.inputs = v; })} offer={isStart ? [] : available}
          title={isStart ? "inputs: what the client supplies" : step.kind === "end" ? "inputs: the procedure's result" : "inputs"} />
      )}
      {(step.kind === "execution" || step.kind === "client_task") && (
        <IOEditor which="outputs" items={step.outputs ?? []} onChange={(v) => set((x) => { x.outputs = v; })} offer={[]} title="outputs" />
      )}
      {step.kind === "decision" && (
        <fieldset data-testid="decision-outputs">
          <legend>outputs (one key per question, and a confidence key where asked)</legend>
          {(step.questions ?? []).length === 0 && <p className="muted small">Add a question and its answer becomes a key.</p>}
          <ul className="criteria">
            {(step.questions ?? []).map((q, i) => <li key={i}><code>{q.name || "(unnamed)"}</code>: {QUESTION_TYPES[q.type]}</li>)}
            {(step.confidence ?? []).filter(Boolean).map((q) => <li key={`c-${q}`}><code>{confidenceKey(q)}</code>: {CONFIDENCE_TYPE}</li>)}
          </ul>
        </fieldset>
      )}

      <div className="actions">
        {runnable && start && !isFirst && <button onClick={onStart} data-testid="make-first">make this the first step</button>}
        {runnable && isFirst && <span className="muted">the start hands to this step</span>}
        <button className="danger" onClick={onDelete}>delete step</button>
      </div>
    </div>
  );
}

/** The help on a router's confidence check, in the panel. */
const CHECK_HELP = "Checked before the branches: when the key is below the bound, or absent (a decision answered by hand writes no confidence) or null, the run goes to the named step instead. One check per router.";

function RouterFields({ draft, step, available, set, target, onPrefill, onAddOnBranch }: {
  draft: Draft; step: Step; available: AvailableKey[]; set: (c: (s: Step) => void) => void; onPrefill: () => void; onAddOnBranch: (index: number, kind: StepKind) => void;
  target: (value: string | undefined, onChange: (v: string | undefined) => void, field?: string, aria?: string) => ReactNode;
}) {
  const branches = step.branches ?? [];
  // The keys a check can read: every float produced anywhere in the draft (a decision's confidence keys, a script's
  // or task's float outputs). A check's key need only be produced on some path to the router.
  const floats = new Map<string, string>();
  for (const s of draft.steps) {
    for (const q of s.confidence ?? []) if (q) floats.set(confidenceKey(q), `${label(s)}'s confidence of ${q}`);
    for (const o of s.outputs ?? []) if (o.name && o.type === CONFIDENCE_TYPE) floats.set(o.name, `output of ${label(s)}`);
  }
  const check = step.check;
  return (
    <>
      <Field name="branch_on" hint={
        step.branchOn && possibleValues(draft, step.branchOn)
          ? <span data-testid="possible-values">possible values: {possibleValues(draft, step.branchOn)!.join(", ")}</span>
          : "the key whose value picks the branch"}>
        <select value={step.branchOn ?? ""} data-field="branchOn" onChange={(e) => set((s) => { s.branchOn = e.target.value || undefined; })}>
          <option value="">(choose a key)</option>
          {available.map((k) => <option key={k.name} value={k.name}>{k.name} ({k.type})</option>)}
          {step.branchOn && !available.some((k) => k.name === step.branchOn) && <option value={step.branchOn}>{step.branchOn} (not produced here)</option>}
        </select>
      </Field>
      <fieldset>
        <legend>branches (value → step)</legend>
        {branches.map((b, i) => (
          <div className="row" key={i}>
            <input type="text" value={b.value} aria-label={`branch ${i + 1} value`} data-field={i === 0 ? "branches" : undefined}
              onChange={(e) => set((s) => { s.branches![i].value = e.target.value; })} />
            {target(b.target, (v) => set((s) => { s.branches![i].target = v; }), undefined, `branch ${i + 1} target`)}
            <button onClick={() => set((s) => { s.branches!.splice(i, 1); })} aria-label={`remove branch ${i + 1}`}>remove</button>
            <div className="add-kinds" role="group" aria-label={`New step on branch ${i + 1}`}>
              {KINDS.map((k) => <button key={k} onClick={() => onAddOnBranch(i, k)}>+ {k}</button>)}
            </div>
          </div>
        ))}
        <div className="actions">
          <button onClick={() => set((s) => { (s.branches ??= []).push({ value: "" }); })}>add branch</button>
          <button onClick={onPrefill}>fill from the decision before</button>
        </div>
      </fieldset>
      <fieldset data-testid="router-check">
        <legend>confidence check</legend>
        <label className="option">
          <input type="checkbox" checked={!!check} data-field="check"
            onChange={(e) => set((s) => { if (e.target.checked) s.check = { key: [...floats.keys()][0] ?? "", below: 0.6 }; else delete s.check; })} /> check a confidence before branching
        </label>
        <p className="hint muted small" data-testid="check-help">{CHECK_HELP}</p>
        {check && (
          <>
            <Field name="key" hint={floats.size ? "a float key: a decision's `<question>_confidence`, or a declared float output" : <span className="error">no float key is produced yet: name a question in a decision's confidence list</span>}>
              <select value={check.key} data-field="check.key" aria-label="check key" onChange={(e) => set((s) => { s.check!.key = e.target.value; })}>
                <option value="">(choose a key)</option>
                {[...floats].map(([k, from]) => <option key={k} value={k}>{k} ({from})</option>)}
                {check.key && !floats.has(check.key) && <option value={check.key}>{check.key} (not produced here)</option>}
              </select>
            </Field>
            <Field name="below" hint="in 0 to 1; a confidence under this bound sends the run to the step below">
              <NumberInput value={check.below} field="check.below" ariaLabel="check below" min={0} max={1} onCommit={(n) => set((s) => { s.check!.below = n; })} />
            </Field>
            <Field name="to" hint="where the run goes when the check fires">
              {target(check.to, (v) => set((s) => { s.check!.to = v; }), "check.to", "check target")}
            </Field>
          </>
        )}
      </fieldset>
    </>
  );
}

/** A number field that keeps what is typed, so `0.` survives on the way to `0.5`, and hands over a number only when
 *  the text is one (or nothing, which clears it). A value outside min and max is marked, and still handed over:
 *  the linter says what is wrong with it. */
function NumberInput({ value, onCommit, ariaLabel, field, min, max }: {
  value: number | undefined; onCommit: (n: number | undefined) => void; ariaLabel: string; field?: string; min?: number; max?: number;
}) {
  const parse = (t: string): number | undefined | null => (t.trim() === "" ? undefined : Number.isFinite(Number(t)) ? Number(t) : null);
  const [text, setText] = useState(value === undefined ? "" : String(value));
  // Follow a change from outside (an undo, a different draft) unless the text already means this value.
  useEffect(() => { if (parse(text) !== value) setText(value === undefined ? "" : String(value)); }, [value]);
  const n = parse(text);
  const bad = n === null || (n !== undefined && ((min !== undefined && n < min) || (max !== undefined && n > max)));
  return (
    <input type="text" inputMode="decimal" value={text} data-field={field} aria-label={ariaLabel} aria-invalid={bad || undefined}
      onChange={(e) => { setText(e.target.value); const v = parse(e.target.value); if (v !== null) onCommit(v); }} />
  );
}

function blankQuestion(type: Question["type"], name: string, instructions = ""): Question {
  if (type === "noul") return { type, name, instructions };
  if (type === "choice") return { type, name, instructions, criteria: [{ label: "", description: null }, { label: "", description: null }] };
  return { type, name, instructions, criteria: ["", ""] };
}

/** The help on a decision's `fallback`, in the panel. */
const FALLBACK_HELP = "On: a client with no decision model may answer the questions by hand; a manual answer writes no confidence, so any route on this step's answers is unmeasured (the linter says so) and a router's check on its confidence fires with reason `absent`. Off (the default): a client with no decision model stops at this step with `no_decision_model` until one is configured.";

function DecisionFields({ step, set }: { step: Step; set: (c: (s: Step) => void) => void }) {
  const questions = step.questions ?? [];
  const q = (i: number, change: (q: Question) => void) => set((s) => change(s.questions![i]));
  const emits = (name: string) => (step.confidence ?? []).includes(name);
  const toggle = (name: string, on: boolean) => set((s) => {
    const list = (s.confidence ?? []).filter((x) => x !== name);
    if (on) list.push(name);
    s.confidence = list.length ? list : undefined;
  });
  return (
    <>
      <fieldset>
        <legend>questions</legend>
        {questions.map((question, i) => (
          <fieldset className="question" key={i} data-testid="question">
            <legend>{question.name || "(unnamed)"}</legend>
            <Text name="name" field={i === 0 ? "questions" : undefined} value={question.name}
              invalid={!/^[A-Za-z_][A-Za-z0-9_]*$/.test(question.name)}
              onChange={(v) => q(i, (x) => { x.name = v; })} />
            <Field name="type">
              <select value={question.type} aria-label={`${question.name} type`}
                onChange={(e) => set((s) => { const old = s.questions![i]; s.questions![i] = blankQuestion(e.target.value as Question["type"], old.name, old.instructions); })}>
                <option value="noul">noul (yes/no)</option><option value="choice">choice</option><option value="score">score</option>
              </select>
            </Field>
            <Text name="instructions" area value={question.instructions} onChange={(v) => q(i, (x) => { x.instructions = v; })} />
            <Criteria question={question} change={(f) => q(i, f)} />
            <button onClick={() => set((s) => { s.questions!.splice(i, 1); })}>remove question</button>
          </fieldset>
        ))}
        <div className="add-kinds" role="group" aria-label="Add question">
          {(["noul", "choice", "score"] as const).map((t) => (
            <button key={t} onClick={() => set((s) => { (s.questions ??= []).push(blankQuestion(t, `question_${(s.questions?.length ?? 0) + 1}`)); })}>+ {t}</button>
          ))}
        </div>
      </fieldset>
      <fieldset data-testid="confidence-picker">
        <legend>confidence</legend>
        <p className="hint muted small">Each ticked question also writes <code>&lt;question&gt;_confidence</code> to the state: the probability the decision model put on its answer, a float in 0 to 1. A router after this step can check it.</p>
        {questions.length === 0 && <p className="muted small">Add a question first.</p>}
        {questions.map((question, i) => (
          <label className="option" key={i}>
            <input type="checkbox" checked={emits(question.name)} disabled={!question.name} aria-label={`emit ${question.name || `question ${i + 1}`} confidence`}
              data-field={i === 0 ? "confidence" : undefined}
              onChange={(e) => toggle(question.name, e.target.checked)} /> emit <code>{confidenceKey(question.name || "…")}</code>
          </label>
        ))}
      </fieldset>
      <fieldset data-testid="fallback">
        <legend>fallback</legend>
        <label className="option">
          <input type="checkbox" checked={!!step.fallback} data-field="fallback" aria-label="fallback"
            onChange={(e) => set((s) => { s.fallback = e.target.checked || undefined; })} /> the client may answer by hand when it has no decision model
        </label>
        <p className="hint muted small" data-testid="fallback-help">{FALLBACK_HELP}</p>
      </fieldset>
      <label className="option">
        <input type="checkbox" checked={!!step.history} onChange={(e) => set((s) => { s.history = e.target.checked || undefined; })} /> history
      </label>
    </>
  );
}

function Criteria({ question, change }: { question: Question; change: (f: (q: Question) => void) => void }) {
  if (question.type === "noul") {
    return (
      <>
        <Text name="criteria: true" value={question.criteria?.true ?? ""} onChange={(v) => change((x) => { if (x.type === "noul") x.criteria = { ...x.criteria, true: v || undefined }; })} />
        <Text name="criteria: false" value={question.criteria?.false ?? ""} onChange={(v) => change((x) => { if (x.type === "noul") x.criteria = { ...x.criteria, false: v || undefined }; })} />
      </>
    );
  }
  if (question.type === "choice") {
    return (
      <fieldset>
        <legend>labels</legend>
        {question.criteria.map((c, i) => (
          <div className="row" key={i}>
            <input type="text" value={c.label} aria-label={`label ${i + 1}`} placeholder="label"
              onChange={(e) => change((x) => { if (x.type === "choice") x.criteria[i].label = e.target.value; })} />
            <input type="text" value={c.description ?? ""} aria-label={`label ${i + 1} description`} placeholder="description"
              onChange={(e) => change((x) => { if (x.type === "choice") x.criteria[i].description = e.target.value || null; })} />
            <button onClick={() => change((x) => { if (x.type === "choice") x.criteria.splice(i, 1); })}>remove</button>
          </div>
        ))}
        <button onClick={() => change((x) => { if (x.type === "choice") x.criteria.push({ label: "", description: null }); })}>add label</button>
      </fieldset>
    );
  }
  return (
    <fieldset>
      <legend>levels (lowest first)</legend>
      {question.criteria.map((c, i) => (
        <div className="row" key={i}>
          <input type="text" value={c} aria-label={`level ${i + 1}`} onChange={(e) => change((x) => { if (x.type === "score") x.criteria[i] = e.target.value; })} />
          <button onClick={() => change((x) => { if (x.type === "score") x.criteria.splice(i, 1); })}>remove</button>
        </div>
      ))}
      <button onClick={() => change((x) => { if (x.type === "score") x.criteria.push(""); })}>add level</button>
    </fieldset>
  );
}

/** Rows of name, type and description. A step's inputs can be taken from the keys available to it, which fills the
 *  name and the type the key has, so the pick cannot disagree with its producer. */
function IOEditor({ which, title, items, offer, onChange }: {
  which: "inputs" | "outputs"; title: string; items: IOItem[]; offer: AvailableKey[]; onChange: (items: IOItem[]) => void;
}) {
  const taken = new Set(items.map((i) => i.name));
  const left = offer.filter((k) => !taken.has(k.name));
  const row = (i: number, change: (x: IOItem) => void) => onChange(items.map((x, j) => { if (j !== i) return x; const c = { ...x }; change(c); return c; }));
  return (
    <fieldset data-testid={`io-${which}`}>
      <legend>{title}</legend>
      {items.map((item, i) => (
        <div className="row" key={i}>
          <input type="text" value={item.name} data-field={`${which}[${i}].name`} aria-label={`${which} ${i + 1} name`} placeholder="name"
            aria-invalid={!item.name || undefined} onChange={(e) => row(i, (x) => { x.name = e.target.value; })} />
          <select value={item.type} data-field={`${which}[${i}].type`} aria-label={`${which} ${i + 1} type`} onChange={(e) => row(i, (x) => { x.type = e.target.value; })}>
            {!(DATA_TYPES as readonly string[]).includes(item.type) && <option value={item.type}>{item.type}</option>}
            {DATA_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <input type="text" value={item.description ?? ""} aria-label={`${which} ${i + 1} description`} placeholder="description"
            onChange={(e) => row(i, (x) => { x.description = e.target.value || undefined; })} />
          <button onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label={`remove ${which} ${i + 1}`}>remove</button>
        </div>
      ))}
      <div className="actions">
        {left.length > 0 && (
          <select value="" aria-label={`add ${which} from the state`}
            onChange={(e) => { const k = left.find((x) => x.name === e.target.value); if (k) onChange([...items, { name: k.name, type: k.type }]); }}>
            <option value="">add a key from the state…</option>
            {left.map((k) => <option key={k.name} value={k.name}>{k.name} ({k.type})</option>)}
          </select>
        )}
        <button data-field={which} onClick={() => onChange([...items, { name: "", type: "string" }])}>add new {which === "inputs" ? "input" : "output"}</button>
      </div>
    </fieldset>
  );
}
