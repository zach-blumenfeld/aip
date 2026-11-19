// The Studio's chat (plan C4): every message runs a procedure. The first message on a new procedure is
// a brief (with the procedure's name, if the person gives one), which runs build_procedure; every later
// one runs edit_procedure with the draft and the instruction. Both run through the launcher driven
// (plan C6): `aip run`, and at each pause the chat model `aip config agent` names answers it with the
// call `aip agent` makes, recorded as agent `studio`; the pane shows the steps as they run and the
// model's calls in plain words. build_procedure's `ask_user` is the person's step: it arrives here as a
// form, and its answers go back through `aip resume`, after which the model goes on. When a run ends
// the page reads the folder it wrote; the pane shows the review and the diff, and the page the scripts
// the model wrote.

import { useRef, useState, type DragEvent } from "react";
import { describe } from "../api/client";
import { runCli, type CliCall, type ModelSettings, type Outcome, type Paused } from "../api/console";
import { diffLines, type LineOp } from "../diff/lines";
import { modelWords, questionsOf, scriptsWritten, stepWords } from "../studio/chat.ts";
import { collect } from "../run/answers";
import { Hunks } from "./Diff";
import { Fields } from "./Run";

/** One message and the run it started. */
export interface Turn {
  id: number;
  kind: "build" | "edit";
  text: string;
  lines: { kind: "step" | "model" | "note"; text: string }[];
  status: "running" | "paused" | "done" | "failed";
  runId: string | null;
  pause: Paused | null;
  error: string | null;
  /** What the run said at its end: build_procedure's review, edit_procedure's changes. */
  review: string | null;
  /** procedure.aip before the run and after it. */
  diff: LineOp[] | null;
  /** The other files the run added or changed. */
  files: string[];
}

/** What the page does for the chat: the call that starts a run, and reading the folder when it stops. */
export interface ChatHost {
  /** The run a message starts: build_procedure for the first brief of a new procedure (`title` is the name the person
   *  gave it, or empty for the model to choose), edit_procedure after. */
  start: (text: string, title: string) => { kind: "build" | "edit"; call: CliCall };
  /** The call that puts a person's answers into a run's pause and runs on. */
  answer: (runId: string, answers: unknown) => CliCall;
  /** A run wrote these scripts (added or changed, under scripts/): the page shows them before the draft runs. */
  wrote: (scripts: string[]) => void;
  /** The run stopped (done, failed, or paused at the person's step): read the folder it wrote. Resolves with the
   *  folder's procedure.aip and text files as they are now. */
  settled: () => Promise<{ source: string; files: Record<string, string> } | null>;
  /** procedure.aip and the text files before the run. */
  before: () => { source: string; files: Record<string, string> };
  /** A build ran to its end: later messages change what it built. */
  built: () => void;
  /** What a run said at its end (its review or its changes): the page keeps what it says each script touches. */
  reviewed?: (review: string) => void;
  onDocuments: (files: File[]) => Promise<string[]>;
}

interface Props {
  host: ChatHost;
  /** Whether the next message is a brief (build) or an instruction (edit). */
  next: "build" | "edit";
  settings: ModelSettings | null;
  documents: string[];
  busy: boolean;
  setBusy: (busy: boolean) => void;
}

export function StudioChat({ host, next, settings, documents, busy, setBusy }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [dropping, setDropping] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const seq = useRef(0);

  const noModel = settings !== null && !settings.agent?.key;
  // A run waiting on the person: the next message waits until it is answered.
  const waiting = turns.some((t) => t.status === "paused");
  const update = (id: number, change: (t: Turn) => Turn) => setTurns((all) => all.map((t) => (t.id === id ? change(t) : t)));
  const say = (id: number, kind: "step" | "model" | "note", line: string) => update(id, (t) => ({ ...t, lines: [...t.lines, { kind, text: line }] }));

  /** Run `call` for the turn, then read what it left. */
  const drive = async (id: number, kind: Turn["kind"], call: CliCall, before: { source: string; files: Record<string, string> }) => {
    setBusy(true);
    update(id, (t) => ({ ...t, status: "running", pause: null, error: null }));
    let outcome: Outcome | null = null;
    try {
      const exit = await runCli(call, {
        onStep: (e) => { const w = stepWords(e); if (w) say(id, "step", w); },
        onModel: (e) => { if (e.event !== "answer") say(id, "model", modelWords(e)); },
        onOutcome: (o) => { outcome = o; },
      });
      const o = outcome as Outcome | null;
      if (!o) {
        update(id, (t) => ({ ...t, status: "failed", error: exit.error ?? (exit.stderr.trim() || `aip exited with ${exit.code ?? exit.signal}`) }));
        return;
      }
      const after = await host.settled();
      const diff = after ? diffLines(before.source, after.source) : null;
      const files = after ? Object.keys(after.files).filter((f) => after.files[f] !== before.files[f]).sort() : [];
      if (after) host.wrote(scriptsWritten(before.files, after.files));
      if ("paused" in o) {
        update(id, (t) => ({ ...t, status: "paused", pause: o, runId: o.run_id }));
      } else if ("done" in o) {
        const r = o.result;
        const review = typeof r.review === "string" ? r.review : typeof r.changes === "string" ? r.changes : null;
        update(id, (t) => ({ ...t, status: "done", runId: o.run_id, review, diff, files }));
        if (review) host.reviewed?.(review);
        if (kind === "build") host.built();
      } else {
        update(id, (t) => ({ ...t, status: "failed", runId: o.run_id, error: `${o.error}: ${o.message}`, diff, files }));
      }
    } catch (e) {
      update(id, (t) => ({ ...t, status: "failed", error: describe(e) }));
    } finally {
      setBusy(false);
    }
  };

  const send = () => {
    const message = text.trim();
    if (!message || busy || waiting) return;
    const name = next === "build" ? title.trim() : "";
    const { kind, call } = host.start(message, name);
    const id = ++seq.current;
    const before = host.before();
    const said = name ? `${message} (name it ${name})` : message;
    setTurns((all) => [...all, { id, kind, text: said, lines: [], status: "running", runId: null, pause: null, error: null, review: null, diff: null, files: [] }]);
    setText("");
    setTitle("");
    beforeOf.current.set(id, before);
    void drive(id, kind, call, before);
  };
  const beforeOf = useRef(new Map<number, { source: string; files: Record<string, string> }>());

  const answer = (turn: Turn, answers: unknown) => {
    if (!turn.runId) return;
    say(turn.id, "note", "you answered");
    void drive(turn.id, turn.kind, host.answer(turn.runId, answers), beforeOf.current.get(turn.id) ?? host.before());
  };

  const drop = async (files: File[]) => {
    setDropping(false);
    if (!files.length) return;
    try { await host.onDocuments(files); setProblem(null); } catch (e) { setProblem(describe(e)); }
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); void drop([...e.dataTransfer.files]); };

  return (
    <section className={`studio-chat${dropping ? " dropping" : ""}`} data-testid="studio-chat"
             onDragOver={(e) => { e.preventDefault(); setDropping(true); }} onDragLeave={() => setDropping(false)} onDrop={onDrop}>
      <h2>Chat</h2>
      {turns.length === 0 && (
        <p className="muted small">
          {next === "build"
            ? "Describe the procedure: what comes in, what is decided and by whom, what goes out. Drop the documents it should follow (a policy, a runbook) here. The model reads them, asks you what they leave open, writes the procedure and compiles it. Give it a name, or leave that to the model, which names it after what it handles."
            : "Say what to change: a step to add, a rule to move, a branch to send elsewhere. The model changes the procedure and compiles it; Undo puts it back."}
        </p>
      )}
      <ol className="turns">
        {turns.map((t) => <TurnView key={t.id} turn={t} busy={busy} onAnswer={(a) => answer(t, a)} />)}
      </ol>
      {documents.length > 0 && (
        <p className="small" data-testid="studio-documents">documents: {documents.map((d, i) => <span key={d}>{i ? ", " : ""}<code>{d.split("/").pop()}</code></span>)}</p>
      )}
      {noModel && (
        <p className="boundary" data-testid="studio-no-model">
          The chat needs a model to answer the runs&apos; steps (<code>aip config agent</code>): set its key under Settings. The model is what reads the documents and writes the procedure.
        </p>
      )}
      {waiting && <p className="muted small" data-testid="studio-waiting">Answer the question above first: the run waits for it.</p>}
      {next === "build" && (
        <label className="form-row small">
          name <input type="text" value={title} disabled={busy || noModel || waiting} data-testid="studio-title" maxLength={64}
                      placeholder="optional: the model names it from what it handles" onChange={(e) => setTitle(e.target.value)} />
        </label>
      )}
      <textarea rows={4} value={text} disabled={busy || noModel || waiting} data-testid="studio-message" aria-label={next === "build" ? "brief" : "instruction"}
                placeholder={next === "build" ? "Describe the procedure…" : "What should change?"} onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }} />
      <div className="actions">
        <button type="button" onClick={send} disabled={busy || noModel || waiting || !text.trim()} data-testid="studio-send">
          {next === "build" ? "Build it" : "Change it"}
        </button>
        <label className="small linkish">
          add documents <input type="file" multiple hidden data-testid="studio-attach" onChange={(e) => void drop([...(e.target.files ?? [])])} />
        </label>
      </div>
      {problem && <p className="error" role="alert">{problem}</p>}
    </section>
  );
}

function TurnView({ turn, busy, onAnswer }: { turn: Turn; busy: boolean; onAnswer: (answers: unknown) => void }) {
  const human = turn.status === "paused" && turn.pause;
  return (
    <li className="turn" data-testid="studio-turn" data-kind={turn.kind} data-status={turn.status} data-run={turn.runId ?? ""}>
      <p className="you"><strong>you</strong> {turn.text}</p>
      <ul className="lines" data-testid="studio-lines">
        {turn.lines.map((l, i) => <li key={i} className={`line ${l.kind}`} data-kind={l.kind}>{l.text}</li>)}
        {turn.status === "running" && <li className="line muted">…</li>}
      </ul>
      {human && <HumanForm pause={turn.pause!} busy={busy} onAnswer={onAnswer} />}
      {turn.status === "failed" && <p className="error" role="alert" data-testid="studio-run-error">{turn.error}</p>}
      {turn.review && (
        <div data-testid="studio-review">
          <h4>{turn.kind === "build" ? "review" : "what changed"}</h4>
          <p className="review">{turn.review}</p>
        </div>
      )}
      {turn.diff && turn.status !== "paused" && turn.diff.some((op) => op.kind !== "equal") && (
        <details className="studio-diff" open data-testid="studio-diff">
          <summary>procedure.aip, before and after</summary>
          <Hunks ops={turn.diff} />
        </details>
      )}
      {turn.files.length > 0 && turn.status !== "paused" && (
        <p className="small muted" data-testid="studio-files">files written: {turn.files.join(", ")}</p>
      )}
    </li>
  );
}

/** A pause the model did not answer: the person's step (build_procedure's ask_user), or a task it gave up on. The
 *  questions it carries, and a field per key it is answered with. */
function HumanForm({ pause, busy, onAnswer }: { pause: Paused; busy: boolean; onAnswer: (answers: unknown) => void }) {
  const task = pause.tasks[0];
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problems, setProblems] = useState<Record<string, string>>({});
  if (!task) return null;
  const questions = questionsOf(task.state);
  const human = pause.answerer?.person !== false;
  const go = () => {
    const made = collect(fields, task.answer_with, task.labels ?? {});
    setProblems(made.problems);
    if (Object.keys(made.problems).length === 0) onAnswer(made.value);
  };
  return (
    <form className="pause human" data-testid="studio-human" data-step={pause.step} onSubmit={(e) => { e.preventDefault(); go(); }}>
      <h4>{human ? "Your turn" : `The model stopped at ${pause.step}`}</h4>
      {!human && pause.answerer && <p className="muted small">{pause.answerer.reason}</p>}
      {questions.length > 0 ? (
        <ol className="questions" data-testid="studio-questions">{questions.map((q, i) => <li key={i}>{q}</li>)}</ol>
      ) : (
        <pre className="task">{task.prompt}</pre>
      )}
      <Fields prefix={`studio-${pause.step}`} types={task.answer_with} labels={task.labels ?? {}} fields={fields} problems={problems} busy={busy}
              onChange={(key, value) => setFields((f) => ({ ...f, [key]: value }))} />
      <div className="actions"><button type="submit" disabled={busy} data-testid="studio-answer">Answer</button></div>
    </form>
  );
}
