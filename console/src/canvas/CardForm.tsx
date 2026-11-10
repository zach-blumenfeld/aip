// The canvas's forms when it edits (plan C2): an open card or loop as the shape spec 2.1 gives it, what it
// reads, the lines of its kind, what it produces, where it goes, each part changeable; and the form that
// adds a card. Every change is one operation of edit.ts, handed to the host as text edits; the form keeps
// nothing but what is being typed. Part of the canvas folder: no console imports (plan E2 bundles it).

import { useEffect, useState, type ReactNode } from "react";
import {
  ADDABLE, addBranch, addCard, addNext, addOutput, addRead, connect, disconnect, EditError, exitsOf, move, readKey, removeItem,
  removeOutput, removeRead, setBound, setText, targetsFor, unrouted, upstreamOf, type AddableKind, type TextEdit,
} from "./edit.ts";
import type { Card, Frame, Graph, Model, Port } from "./model.ts";

export interface Editing {
  /** Called with one operation's text edits and a phrase that says what they do. */
  onEdit: (edits: TextEdit[], what: string) => void;
  /** The bundle's scripts, offered to a new `Execute` card. */
  scripts?: string[];
  /** The text of the bundle's files by path: a `Task_Agent`'s prompt file is edited here. */
  files?: Record<string, string>;
  /** Called with a file's new text. */
  onFile?: (path: string, text: string) => void;
}

interface FormProps {
  item: Card | Frame;
  graph: Graph;
  model: Model;
  source: string;
  editing: Editing;
  onClose: () => void;
  children?: ReactNode;
}

const str = (v: unknown) => (typeof v === "string" ? v : "");

/** Run an operation; an `EditError` is the form's to say, anything else is a bug and thrown. */
function attempt(editing: Editing, what: string, make: () => TextEdit[], fail: (m: string) => void) {
  try {
    editing.onEdit(make(), what);
    fail("");
  } catch (e) {
    if (e instanceof EditError) fail(e.message);
    else throw e;
  }
}

export function CardForm({ item, graph, model, source, editing, onClose, children }: FormProps) {
  const [error, setError] = useState("");
  const node = graph.nodes.find((n) => n.id === item.id);
  const kind = item.kind;
  const isCard = "sections" in item;
  const run = (what: string, make: () => TextEdit[]) => attempt(editing, what, make, setError);
  const targets = targetsFor(graph, item.id);
  const exits = exitsOf(graph, item.id);
  const loops = Object.values(model.frames).filter((f) => f.id !== item.parent && f.id !== item.id);

  return (
    <aside className="aipc-detail aipc-form" data-testid="card-form" data-name={item.name} data-kind={kind}>
      <div className="aipc-detail-head">
        <span className="aipc-kind">{kind}</span> <code>{item.name}</code>
        <button type="button" onClick={onClose} aria-label="close">×</button>
      </div>
      {error && <p className="aipc-error" role="alert" data-testid="form-error">{error}</p>}
      {item.problems && item.problems.length > 0 && (
        <ul className="aipc-problems" data-testid="form-problems">{item.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
      )}

      {isCard && (
        <FormSection label="description">
          <TextField value={str(node?.properties.description)} testid="form-description" multiline
                     onSave={(text) => run(`describe ${item.name}`, () => setText(source, graph, item.id, text))} />
        </FormSection>
      )}
      {!isCard && <p className="aipc-detail-title"><code>{(item as Frame).header}</code></p>}

      {isCard && kind !== "Start" && <Reads card={item as Card} graph={graph} run={run} source={source} />}

      {kind === "Decide" && <Questions step={item.id} graph={graph} run={run} source={source} />}
      {kind === "Task_Agent" && <PromptFile step={item.id} graph={graph} editing={editing} />}
      {(kind === "Execute" || kind === "Task_Agent" || kind === "Start") && <Outputs card={item as Card} graph={graph} run={run} source={source} />}

      <FormSection label="then">
        <ul className="aipc-form-ports">
          {item.ports.map((port, i) => (
            <PortRow key={i} port={port} targets={targets} graph={graph}
                     onTarget={(target) => {
                       if (port.target === "") {
                         run(port.kind === "branch" ? `branch ${port.label} of ${item.name}` : `next of ${item.name}`,
                             () => port.kind === "branch" ? addBranch(source, graph, item.id, port.label, target) : addNext(source, graph, item.id, target));
                       } else {
                         const edge = exits.find((e) => (e.properties.line ?? null) === port.line);
                         if (edge) run(`connect ${item.name} ${port.label}`, () => connect(source, edge, target));
                       }
                     }}
                     onDisconnect={port.target === "" ? undefined : () => {
                       const edge = exits.find((e) => (e.properties.line ?? null) === port.line);
                       if (edge) run(`disconnect ${item.name} ${port.label}`, () => disconnect(source, edge));
                     }} />
          ))}
        </ul>
        {kind === "Route" && <AddBranch route={item.id} graph={graph} targets={targets} run={run} source={source} />}
        {item.ports.length === 0 && kind !== "End" && kind !== "Route" && (
          <AddNext targets={targets} onAdd={(t) => run(`next of ${item.name}`, () => addNext(source, graph, item.id, t))} />
        )}
      </FormSection>

      {(kind === "Route" && graph.edges.some((e) => e.start === item.id && e.type === "BELOW")) && (
        <FormSection label="confidence check">
          <NumberField value={Number(node?.properties.check_below ?? 0.8)} step={0.05} testid="form-bound"
                       onSave={(v) => run(`bound of ${item.name}`, () => setBound(source, graph, item.id, v))} />
        </FormSection>
      )}
      {!isCard && node?.properties.at_most !== undefined && node?.properties.at_most !== null && (
        <FormSection label="at most">
          <NumberField value={Number(node.properties.at_most)} step={1} testid="form-cap"
                       onSave={(v) => run(`cap of ${item.name}`, () => setBound(source, graph, item.id, v))} />
        </FormSection>
      )}

      {kind !== "Start" && kind !== "End" && (
        <FormSection label="move">
          {item.parent && (
            <button type="button" data-testid="form-move-out" onClick={() => run(`move ${item.name} out`, () => move(source, graph, item.id, null))}>
              Move out of {model.frames[item.parent]?.name}
            </button>
          )}
          {loops.length > 0 && (
            <select data-testid="form-move-into" value="" aria-label="move into a loop"
                    onChange={(e) => e.target.value && run(`move ${item.name} into ${model.frames[e.target.value]?.name}`, () => move(source, graph, item.id, e.target.value))}>
              <option value="">Move into a loop…</option>
              {loops.map((f) => <option key={f.id} value={f.id}>{f.kind} {f.name}</option>)}
            </select>
          )}
          <button type="button" className="aipc-danger" data-testid="form-remove"
                  onClick={() => { run(`remove ${item.name}`, () => removeItem(source, graph, item.id)); onClose(); }}>
            Remove {isCard ? "card" : "loop"}
          </button>
        </FormSection>
      )}
      {children}
    </aside>
  );
}

type Run = (what: string, make: () => TextEdit[]) => void;

function FormSection({ label, children }: { label: string; children: ReactNode }) {
  return <div className="aipc-detail-section" data-form={label}><div className="aipc-label">{label}</div>{children}</div>;
}

function Reads({ card, graph, run, source }: { card: Card; graph: Graph; run: Run; source: string }) {
  const reads = graph.edges.filter((e) => e.end === card.id && e.type === "READ_BY" && e.properties.interpolated !== true && typeof e.properties.line === "number")
    .map((e) => readKey(graph, e));
  const offers = upstreamOf(graph, card.id).map((o) => o.key).filter((k) => !reads.includes(k));
  const [pick, setPick] = useState("");
  return (
    <FormSection label="reads">
      <ul className="aipc-chips">
        {reads.map((k) => (
          <li key={k} data-testid="form-read" data-key={k}><code>{k}</code>
            <button type="button" aria-label={`stop reading ${k}`} onClick={() => run(`unread ${k}`, () => removeRead(source, graph, card.id, k))}>×</button></li>
        ))}
      </ul>
      {reads.length === 0 && offers.length === 0 && <p className="aipc-note">Nothing yet: no key is produced on the way here.</p>}
      {offers.length > 0 && (
        <span className="aipc-inline">
          <select value={pick} onChange={(e) => setPick(e.target.value)} data-testid="form-read-pick" aria-label="a key to read">
            <option value="">a key produced upstream…</option>
            {offers.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <button type="button" disabled={!pick} data-testid="form-read-add"
                  onClick={() => { run(`read ${pick}`, () => addRead(source, graph, card.id, pick)); setPick(""); }}>Read</button>
        </span>
      )}
    </FormSection>
  );
}

function Questions({ step, graph, run, source }: { step: string; graph: Graph; run: Run; source: string }) {
  const questions = graph.edges.filter((e) => e.start === step && e.type === "ASKS")
    .map((e) => graph.nodes.find((n) => n.id === e.end)).filter((n) => n !== undefined);
  return (
    <FormSection label="asks">
      {questions.map((q) => (
        <div key={q.id} className="aipc-question" data-testid="form-question" data-question={str(q.properties.name)}>
          <code>{str(q.properties.name)}: {str(q.properties.type)}{Array.isArray(q.properties.labels) ? ` [${(q.properties.labels as string[]).join(", ")}]` : ""}</code>
          <TextField value={str(q.properties.instruction)} multiline testid="form-instruction"
                     onSave={(text) => run(`ask ${str(q.properties.name)}`, () => setText(source, graph, q.id, text))} />
        </div>
      ))}
    </FormSection>
  );
}

function PromptFile({ step, graph, editing }: { step: string; graph: Graph; editing: Editing }) {
  const file = graph.edges.find((e) => e.start === step && e.type === "PROMPTED_BY");
  const path = str(graph.nodes.find((n) => n.id === file?.end)?.properties.path);
  if (!path) return <p className="aipc-note">No <code>Prompt</code> file: the description is the prompt.</p>;
  const text = editing.files?.[path];
  return (
    <FormSection label={`prompt, ${path}`}>
      {text === undefined || !editing.onFile
        ? <p className="aipc-note">The prompt is the file <code>{path}</code>.</p>
        : <TextField value={text} multiline rows={8} testid="form-prompt" onSave={(t) => editing.onFile!(path, t)} />}
    </FormSection>
  );
}

const TYPES = ["string", "integer", "float", "boolean", "list", "object", "true_or_false", "choice [a, b]", "score [low, high]"];

function Outputs({ card, graph, run, source }: { card: Card; graph: Graph; run: Run; source: string }) {
  const keys = graph.edges.filter((e) => e.start === card.id && e.type === "PRODUCES")
    .map((e) => graph.nodes.find((n) => n.id === e.end)).filter((n) => n !== undefined)
    .map((n) => ({ name: str(n.properties.name), type: str(n.properties.type) }));
  const [name, setName] = useState("");
  const [type, setType] = useState("string");
  const [description, setDescription] = useState("");
  const isStart = card.kind === "Start";
  const valid = /^[a-z][a-z0-9_]*$/.test(name);
  return (
    <FormSection label={isStart ? "inputs" : "produces"}>
      <ul className="aipc-chips">
        {keys.map((k) => (
          <li key={k.name} data-testid="form-output" data-key={k.name}><code>{k.name}: {k.type}</code>
            <button type="button" aria-label={`remove ${k.name}`} onClick={() => run(`unproduce ${k.name}`, () => removeOutput(source, graph, card.id, k.name))}>×</button></li>
        ))}
      </ul>
      <span className="aipc-inline">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name" aria-label="the key's name" data-testid="form-output-name" size={12} />
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="its type" data-testid="form-output-type">
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="what it holds" aria-label="its description" size={18} />
        <button type="button" disabled={!valid} data-testid="form-output-add"
                onClick={() => { run(`produce ${name}`, () => addOutput(source, graph, card.id, { name, type, description })); setName(""); setDescription(""); }}>
          Add
        </button>
      </span>
    </FormSection>
  );
}

function PortRow({ port, targets, graph, onTarget, onDisconnect }:
                 { port: Port; targets: string[]; graph: Graph; onTarget: (t: string) => void; onDisconnect?: () => void }) {
  const current = port.target === "" ? "" : port.kind === "continue" || port.quote.startsWith("the next pass of")
    ? "Continue" : str(graph.nodes.find((n) => n.id === port.target)?.properties.name) || (port.target === "step:end" ? "end" : port.target);
  const options = current && !targets.includes(current) ? [current, ...targets] : targets;
  return (
    <li className={port.problem ? "aipc-bad" : undefined} data-testid="form-port" data-port={port.label} data-target={current}>
      <span className="aipc-port-label">{port.label}</span> →{" "}
      <select value={current} onChange={(e) => e.target.value && onTarget(e.target.value)} aria-label={`where ${port.label} leads`} data-testid="port-target">
        {current === "" && <option value="">nowhere yet…</option>}
        {options.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      {onDisconnect && <button type="button" aria-label={`disconnect ${port.label}`} data-testid="port-disconnect" onClick={onDisconnect}>×</button>}
      {port.problem && <div className="aipc-note aipc-bad">{port.problem}</div>}
    </li>
  );
}

function AddBranch({ route, graph, targets, run, source }: { route: string; graph: Graph; targets: string[]; run: Run; source: string }) {
  const { labels, checked } = unrouted(graph, route);
  const choices = [...labels, ...(checked ? [] : ["Confidence_Below"])];
  const [label, setLabel] = useState("");
  const [target, setTarget] = useState("");
  if (choices.length === 0) return null;
  return (
    <span className="aipc-inline" data-testid="form-add-branch">
      <select value={label} onChange={(e) => setLabel(e.target.value)} aria-label="a value with no branch">
        <option value="">add a branch…</option>
        {choices.map((l) => <option key={l} value={l}>{l === "Confidence_Below" ? "the confidence check" : l}</option>)}
      </select>
      <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="where it leads">
        <option value="">to…</option>
        {targets.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      <button type="button" disabled={!label || !target}
              onClick={() => run(`branch ${label}`, () => addBranch(source, graph, route, label === "Confidence_Below" ? null : label, target))}>Add</button>
    </span>
  );
}

function AddNext({ targets, onAdd }: { targets: string[]; onAdd: (t: string) => void }) {
  return (
    <select value="" onChange={(e) => e.target.value && onAdd(e.target.value)} aria-label="where it goes" data-testid="form-add-next">
      <option value="">where it goes…</option>
      {targets.map((t) => <option key={t} value={t}>{t}</option>)}
    </select>
  );
}

/** A text kept as typed until "Change" (or leaving it), so every keystroke is not a compile. */
function TextField({ value, onSave, multiline = false, rows = 3, testid }:
                   { value: string; onSave: (v: string) => void; multiline?: boolean; rows?: number; testid?: string }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const changed = text !== value;
  return (
    <span className="aipc-field">
      {multiline
        ? <textarea value={text} rows={rows} onChange={(e) => setText(e.target.value)} data-testid={testid} />
        : <input value={text} onChange={(e) => setText(e.target.value)} data-testid={testid} />}
      <button type="button" disabled={!changed} onClick={() => onSave(text)} data-testid={testid ? `${testid}-save` : undefined}>Change</button>
    </span>
  );
}

function NumberField({ value, step, onSave, testid }: { value: number; step: number; onSave: (v: number) => void; testid?: string }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const n = Number(text);
  return (
    <span className="aipc-field">
      <input type="number" step={step} value={text} onChange={(e) => setText(e.target.value)} data-testid={testid} />
      <button type="button" disabled={!Number.isFinite(n) || n === value} onClick={() => onSave(n)} data-testid={testid ? `${testid}-save` : undefined}>Change</button>
    </span>
  );
}

// ------------------------------------------------------------------ adding a card

interface AddProps { graph: Graph; model: Model; source: string; editing: Editing; after: string | null; onAdded: (name: string) => void; onClose: () => void }

/** The form that adds a card: its kind, its description (its name comes from it), where it is written and where it goes. */
export function AddCardForm({ graph, model, source, editing, after: initial, onAdded, onClose }: AddProps) {
  const items = [...Object.values(model.cards), ...Object.values(model.frames)]
    .filter((i) => i.kind !== "End").sort((a, b) => (a.line ?? 0) - (b.line ?? 0));
  const fallback = items.filter((i) => i.parent === null).at(-1)?.id ?? "";
  const [kind, setKind] = useState<AddableKind>("Task_Agent");
  const [description, setDescription] = useState("");
  const [after, setAfter] = useState(initial && items.some((i) => i.id === initial) ? initial : fallback);
  const targets = after ? targetsFor(graph, after) : [];
  const picked = items.find((i) => i.id === after);
  // By default it goes where the card written after it starts: what reads on from the new one.
  const following = picked ? [...Object.values(model.cards), ...Object.values(model.frames)]
    .filter((i) => i.parent === picked.parent && (i.line ?? 0) > (picked.line ?? 0)).sort((a, b) => (a.line ?? 0) - (b.line ?? 0))[0] : undefined;
  const [next, setNext] = useState("");
  const offers = after ? upstreamOf(graph, after, true) : [];
  const answers = offers.filter((o) => (kind === "Aggregate" ? o.type === "true_or_false" : o.labels.length > 0));
  const [answer, setAnswer] = useState("");
  const scripts = editing.scripts ?? [];
  const [script, setScript] = useState(scripts[0] ?? "");
  const [error, setError] = useState("");
  const target = next || (following && targets.includes(following.name) ? following.name : targets.at(-1)) || "end";

  const submit = () => {
    try {
      const picked = answers.find((a) => a.key === answer);
      const made = addCard(source, graph, { kind, description, after, next: target, script: script || undefined, answer: picked?.key, labels: picked?.labels });
      editing.onEdit(made.edits, `add ${kind} ${made.name}`);
      onAdded(made.name);
    } catch (e) {
      if (e instanceof EditError) setError(e.message);
      else throw e;
    }
  };

  return (
    <aside className="aipc-detail aipc-form" data-testid="card-add">
      <div className="aipc-detail-head"><strong>Add a card</strong><button type="button" onClick={onClose} aria-label="close">×</button></div>
      {error && <p className="aipc-error" role="alert">{error}</p>}
      <FormSection label="kind">
        <select value={kind} onChange={(e) => setKind(e.target.value as AddableKind)} data-testid="add-kind" aria-label="kind">
          {ADDABLE.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </FormSection>
      <FormSection label="description">
        <textarea value={description} rows={2} onChange={(e) => setDescription(e.target.value)} data-testid="add-description"
                  placeholder="What the step does; its name is made from it" />
      </FormSection>
      <FormSection label="written after">
        <select value={after} onChange={(e) => { setAfter(e.target.value); setNext(""); }} data-testid="add-after" aria-label="written after">
          {items.map((i) => <option key={i.id} value={i.id}>{i.kind} {i.name}</option>)}
        </select>
      </FormSection>
      {kind === "Execute" && (
        <FormSection label="script">
          <select value={script} onChange={(e) => setScript(e.target.value)} aria-label="script">
            {scripts.map((s) => <option key={s} value={s}>{s}</option>)}
            <option value="">a new one (scripts/&lt;name&gt;.py, to be added)</option>
          </select>
        </FormSection>
      )}
      {(kind === "Route" || kind === "Aggregate") && (
        <FormSection label={kind === "Route" ? "routes on" : "aggregates"}>
          <select value={answer} onChange={(e) => setAnswer(e.target.value)} data-testid="add-answer" aria-label="the answer">
            <option value="">an answer produced upstream…</option>
            {answers.map((a) => <option key={a.key} value={a.key}>{a.key}{a.labels.length ? ` [${a.labels.join(", ")}]` : ""}</option>)}
          </select>
        </FormSection>
      )}
      {kind !== "Route" && (
        <FormSection label="next step">
          <select value={target} onChange={(e) => setNext(e.target.value)} data-testid="add-next" aria-label="next step">
            {targets.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </FormSection>
      )}
      {kind === "Route" && (
        <FormSection label="every branch to">
          <select value={target} onChange={(e) => setNext(e.target.value)} data-testid="add-next" aria-label="every branch to">
            {targets.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </FormSection>
      )}
      <p><button type="button" disabled={!after || !description.trim()} onClick={submit} data-testid="add-submit">Add {kind} card</button></p>
    </aside>
  );
}
