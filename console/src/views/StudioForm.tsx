// The Studio's form for the step or loop picked on the graph (plan C4): what a person changes by hand.
// A step's description, a Task_Agent's prompt, a question's wording and labels, the labels of an answer
// a step produces, a route's confidence bar, where each way out leads among the steps there are; a
// loop's cap, its Until and what it does at the cap. Each change is a text edit at a span
// (studio/edit.ts) that the page applies, formats and compiles before the graph is drawn again.
// Anything structural is the chat's.

import { useEffect, useState, type ReactNode } from "react";
import type { Diagnostic } from "../api/console";
import type { Graph, GraphEdge } from "../graph/bundle.ts";
import {
  connect, EditError, exitsOf, setAtCap, setBound, setLabels, setText, setUntil, targetsFor, type TextEdit,
} from "../studio/edit.ts";

interface Props {
  graph: Graph;
  source: string;
  id: string;
  /** The draft's text files, by path: a Task_Agent's prompt is one. */
  files: Record<string, string>;
  diagnostics: Diagnostic[];
  /** The path of the script a step runs that the draft does not have. */
  missingScript: string | null;
  busy: boolean;
  onEdit: (edits: TextEdit[], what: string) => void;
  onFile: (path: string, text: string) => void;
  onClose: () => void;
}

const str = (v: unknown) => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));
const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);

export function StudioForm({ graph, source, id, files, diagnostics, missingScript, busy, onEdit, onFile, onClose }: Props) {
  const node = graph.nodes.find((n) => n.id === id);
  const [problem, setProblem] = useState("");
  useEffect(() => setProblem(""), [id]);
  if (!node) return null;
  const p = node.properties;
  const name = str(p.name);
  const loop = node.labels.includes("Loop");
  const kind = loop ? str(p.kind) || "Loop" : str(p.kind);
  const nameOf = (nid: string) => str(graph.nodes.find((n) => n.id === nid)?.properties.name) || nid.replace(/^[a-z]+:/, "");

  const run = (what: string, make: () => TextEdit[]) => {
    try { onEdit(make(), what); setProblem(""); } catch (e) { if (e instanceof EditError) setProblem(e.message); else throw e; }
  };

  const questions = graph.edges.filter((e) => e.start === id && e.type === "ASKS")
    .sort((a, b) => Number(a.properties.order ?? 0) - Number(b.properties.order ?? 0))
    .map((e) => graph.nodes.find((n) => n.id === e.end)!).filter(Boolean);
  const answers = kind === "Decide" ? [] : graph.edges.filter((e) => e.start === id && e.type === "PRODUCES")
    .map((e) => graph.nodes.find((n) => n.id === e.end)!).filter((n) => n && list(n.properties.labels).length > 0);
  const prompt = graph.edges.filter((e) => e.start === id && e.type === "PROMPTED_BY")
    .map((e) => str(graph.nodes.find((n) => n.id === e.end)?.properties.path))[0];
  const mine = diagnostics.filter((d) => d.step === name);

  return (
    <aside className="studio-form" data-testid="studio-form" data-name={name} data-kind={kind}>
      <h3>
        <span className={`kind-tag${loop ? " loop" : ""}`} style={loop ? undefined : { ["--kind" as string]: `var(--${kind})` }}>{kind}</span>{" "}
        <code>{name}</code>
        <button type="button" onClick={onClose} aria-label="close">×</button>
      </h3>
      {missingScript && (
        <p className="boundary" data-testid="needs-script">
          Needs a script: <code>{missingScript}</code> is not in the draft. Ask a developer to write it; the chat can describe what it should do.
        </p>
      )}
      {mine.length > 0 && (
        <ul className="issues" data-testid="form-diagnostics">
          {mine.map((d, i) => <li key={i} data-severity={d.severity} data-code={d.code}><code>{d.code}</code> {d.message}</li>)}
        </ul>
      )}
      {!loop && (
        <TextField label="what it does" value={str(p.description)} testid="form-description" busy={busy}
                   onSave={(v) => run(`describe ${name}`, () => setText(source, graph, id, v))} />
      )}
      {prompt && files[prompt] !== undefined && (
        <TextField label={`prompt (${prompt})`} value={files[prompt]} rows={8} testid="form-prompt" busy={busy}
                   onSave={(v) => onFile(prompt, v)} />
      )}
      {questions.map((q) => (
        <fieldset key={q.id} className="question" data-testid="form-question" data-question={str(q.properties.name)}>
          <legend><code>{str(q.properties.name)}</code> <span className="muted small">{str(q.properties.type)}</span></legend>
          <TextField label="the question" value={str(q.properties.instruction)} testid="form-instruction" busy={busy}
                     onSave={(v) => run(`reword ${str(q.properties.name)}`, () => setText(source, graph, q.id, v))} />
          {list(q.properties.labels).length > 0 && (
            <LabelsField labels={list(q.properties.labels)} busy={busy}
                         onSave={(labels) => run(`labels of ${str(q.properties.name)}`, () => setLabels(source, graph, q.id, labels))} />
          )}
        </fieldset>
      ))}
      {answers.map((a) => (
        <fieldset key={a.id} className="question" data-testid="form-answer" data-key={str(a.properties.name)}>
          <legend><code>{str(a.properties.name)}</code> <span className="muted small">{str(a.properties.type)}</span></legend>
          <LabelsField labels={list(a.properties.labels)} busy={busy}
                       onSave={(labels) => run(`labels of ${str(a.properties.name)}`, () => setLabels(source, graph, a.id, labels))} />
        </fieldset>
      ))}
      {loop && <LoopFields graph={graph} source={source} id={id} busy={busy} run={run} />}
      <Exits graph={graph} source={source} id={id} busy={busy} run={run} nameOf={nameOf} />
      {problem && <p className="error" role="alert" data-testid="form-problem">{problem}</p>}
    </aside>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <label className="form-row"><span className="muted small">{label}</span>{children}</label>;
}

function TextField({ label, value, rows = 2, testid, busy, onSave }: { label: string; value: string; rows?: number; testid: string; busy: boolean; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <div className="form-field" data-testid={testid}>
      <Row label={label}><textarea rows={rows} value={v} onChange={(e) => setV(e.target.value)} /></Row>
      <button type="button" disabled={busy || v === value} onClick={() => onSave(v)} data-testid={`${testid}-save`}>Change</button>
    </div>
  );
}

/** An answer's labels as one line, `angry, calm`: a word renamed in its place is renamed on the routes too. */
function LabelsField({ labels, busy, onSave }: { labels: string[]; busy: boolean; onSave: (labels: string[]) => void }) {
  const text = labels.join(", ");
  const [v, setV] = useState(text);
  useEffect(() => setV(text), [text]);
  return (
    <div className="form-field" data-testid="form-labels">
      <Row label="labels, in order (a word changed in its place is renamed where a route branches on it)">
        <input type="text" value={v} onChange={(e) => setV(e.target.value)} data-testid="form-labels-input" />
      </Row>
      <button type="button" disabled={busy || v === text} onClick={() => onSave(v.split(",").map((s) => s.trim()).filter(Boolean))}
              data-testid="form-labels-save">Change</button>
    </div>
  );
}

type Run = (what: string, make: () => TextEdit[]) => void;

function LoopFields({ graph, source, id, busy, run }: { graph: Graph; source: string; id: string; busy: boolean; run: Run }) {
  const p = graph.nodes.find((n) => n.id === id)!.properties;
  const name = str(p.name);
  const cap = p.at_most ?? p.times;
  const until = p.until_answer ? [
    str(p.until_answer),
    p.until_operator ? `${str(p.until_operator)} ${str(p.until_value)}` : "",
    p.until_confidence_above !== undefined && p.until_confidence_above !== null ? `With Confidence_Above ${str(p.until_confidence_above)}` : "",
  ].filter(Boolean).join(" ") : null;
  const [c, setC] = useState(str(cap));
  useEffect(() => setC(str(cap)), [cap]);
  return (
    <>
      {cap !== undefined && cap !== null && (
        <div className="form-field" data-testid="form-cap">
          <Row label={p.times !== undefined && p.times !== null ? "passes" : "at most this many passes"}>
            <input type="number" min={1} value={c} onChange={(e) => setC(e.target.value)} data-testid="form-cap-input" />
          </Row>
          <button type="button" disabled={busy || c === str(cap) || !(Number(c) >= 1)} onClick={() => run(`cap of ${name}`, () => setBound(source, graph, id, Number(c)))}
                  data-testid="form-cap-save">Change</button>
        </div>
      )}
      {until !== null && (
        <>
          <TextField label="until (an answer, optionally == a label and With Confidence_Above a bar)" value={until} rows={1} testid="form-until" busy={busy}
                     onSave={(v) => run(`until of ${name}`, () => setUntil(source, graph, id, v))} />
          <Row label="when the cap is reached first">
            <select value={str(p.at_cap) || "Else_Fail"} disabled={busy} data-testid="form-at-cap"
                    onChange={(e) => run(`at the cap of ${name}`, () => setAtCap(source, graph, id, e.target.value as "Else_Fail" | "Else_Exit"))}>
              <option value="Else_Fail">fail the run</option>
              <option value="Else_Exit">carry on after the loop</option>
            </select>
          </Row>
        </>
      )}
    </>
  );
}

/** Each way out: where it leads, picked among the steps of the same block; a route's check with its bar. */
function Exits({ graph, source, id, busy, run, nameOf }: { graph: Graph; source: string; id: string; busy: boolean; run: Run; nameOf: (id: string) => string }) {
  const exits = exitsOf(graph, id);
  if (exits.length === 0) return null;
  const targets = targetsFor(graph, id);
  const targetOf = (e: GraphEdge) => (e.type === "CONTINUES" || e.properties.continues === true ? "Continue" : nameOf(e.end));
  return (
    <fieldset className="question" data-testid="form-exits">
      <legend>where it goes next</legend>
      {exits.map((e, i) => {
        const label = e.type === "BRANCH" ? `when ${str(e.properties.value)}` : e.type === "BELOW" ? "when the confidence is below" : "next";
        const current = targetOf(e);
        const options = targets.includes(current) ? targets : [current, ...targets];
        return (
          <div key={i} className="form-exit" data-testid="form-exit" data-way={e.type === "BRANCH" ? str(e.properties.value) : e.type.toLowerCase()}>
            <span className="muted small">{label}</span>
            {e.type === "BELOW" && <Bar value={Number(e.properties.below)} busy={busy} onSave={(v) => run(`bar of ${nameOf(id)}`, () => setBound(source, graph, id, v))} />}
            <select value={current} disabled={busy} data-testid="form-exit-target"
                    onChange={(ev) => run(`${nameOf(id)} ${label} goes to ${ev.target.value}`, () => connect(source, e, ev.target.value))}>
              {options.map((t) => <option key={t} value={t}>{t === "Continue" ? "the next pass" : t}</option>)}
            </select>
          </div>
        );
      })}
    </fieldset>
  );
}

function Bar({ value, busy, onSave }: { value: number; busy: boolean; onSave: (v: number) => void }) {
  const [v, setV] = useState(String(value));
  useEffect(() => setV(String(value)), [value]);
  const n = Number(v);
  return (
    <span data-testid="form-bar">
      <input type="number" step={0.05} min={0} max={1} value={v} onChange={(e) => setV(e.target.value)} data-testid="form-bar-input" />
      <button type="button" disabled={busy || n === value || !(n > 0 && n < 1)} onClick={() => onSave(n)} data-testid="form-bar-save">Change</button>
    </span>
  );
}
