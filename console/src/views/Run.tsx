import { useEffect, useState, type ReactNode } from "react";
import { api, describe, graphOf } from "../api/client";
import {
  cancelCli, consoleConfig, describeProcedure, folderGraph, isFolderMode, localRun, modelSettings, runCli, sessionId,
  type CliCall, type Failed, type ModelSettings, type Outcome, type Paused, type StepEvent,
} from "../api/console";
import type { CatalogEntry, Description, RunRecord, Task } from "../api/types";
import type { Graph } from "../graph/bundle.ts";
import { answersFor, candidatesOf, collect, fieldKind, fieldText, optionsOf, passLabel, rowText } from "../run/answers.ts";
import { agentSteps, type AgentStep } from "../run/human.ts";
import { duration } from "../record/model.ts";
import { href } from "../router";
import { toolWords } from "../studio/chat.ts";
import { RecordHistory, RecordSummary, ErrorSummary, Json, DraftBadge } from "./Record";
import { RunPath } from "./Steps";

/** The run console. Runs go through the `aip` CLI on this machine (`aip run --progress`, then `aip resume
 *  --progress` per answer; or `aip runah`, runah's model answering every task but the human steps' picked here,
 *  plan C5): scripts run here, the decision model is the one this machine's `aip config` names, and the CLI records
 *  the run on the console's server as agent `console` in this tab's session, or `studio` when the Studio's Run
 *  button opened it (`studio`). */
export function Run({ reference, studio = false }: { reference?: string; studio?: boolean }) {
  if (isFolderMode()) return <Console key="folder" />;
  if (!reference) return <Picker />;
  return <Console key={reference} reference={reference} studio={studio} />;
}

function Picker() {
  const [entries, setEntries] = useState<CatalogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.catalog().then(setEntries).catch((e: unknown) => setError(describe(e))); }, []);
  if (error) return <p className="error" role="alert">{error}</p>;
  if (!entries) return <p className="muted">Loading the catalog…</p>;
  return (
    <article>
      <h1>Run a procedure</h1>
      <p>Pick a procedure; the pinned revision runs, else the latest.</p>
      {entries.length === 0 && <p className="muted">Nothing is published. <code>aip publish FOLDER</code> publishes a procedure.</p>}
      <ul className="picker">
        {entries.map((c) => (
          <li key={c.name}>
            {c.resolves === null
              ? <><code className="muted">{c.name}</code><span className="muted"> — every revision is retired; nothing to run</span></>
              : <>
                  <a href={href({ page: "run", ref: c.name })}><code>{c.name}</code></a>
                  <span className="muted"> @{c.resolves}{c.pinned ? " (pinned)" : ""} — {c.description}</span>
                </>}
          </li>
        ))}
      </ul>
    </article>
  );
}

// ------------------------------------------------------------------ the session

type Status = "not started" | "running" | "paused" | "done" | "failed" | "cancelled";

/** A line of the trace: a step as `--progress` reports it, or a tool call of runah's model, in words. */
type TraceLine = StepEvent | { event: "tool"; step: string; words: string };

function Console({ reference, studio = false }: { reference?: string; studio?: boolean }) {
  const folder = isFolderMode();
  const [about, setAbout] = useState<Description | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [steps, setSteps] = useState<TraceLine[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [record, setRecord] = useState<RunRecord | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [process, setProcess] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  /** The procedure's Task_Agent steps (from its graph), runah's model as `aip config` names it, and how to run:
   *  `ahead` is `aip runah` with `human` the steps a person answers; else `aip run`, every task pausing. */
  const [agents, setAgents] = useState<AgentStep[] | null>(null);
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [ahead, setAhead] = useState(studio);
  const [human, setHuman] = useState<string[]>([]);
  /** Whether the run on the page was started run ahead: its answers go back through `aip runah <run id>`. */
  const [ranAhead, setRanAhead] = useState(false);

  useEffect(() => {
    describeProcedure(reference).then(setAbout).catch((e: unknown) => setLoadError(describe(e)));
    modelSettings().then(setSettings).catch(() => setSettings(null));
    const graph: Promise<Graph | null> = folder ? folderGraph().then((g) => g.graph) : reference ? graphOf(reference).then((b) => b.graph) : Promise.resolve(null);
    graph.then((g) => {
      const found = g ? agentSteps(g) : [];
      setAgents(found);
      setHuman(found.filter((s) => s.person).map((s) => s.name));
    }).catch(() => setAgents([]));
  }, [reference, folder]);

  const call = async (what: CliCall) => {
    setRunning(true);
    setCancelled(false);
    setProblem(null);
    setOutcome(null);
    let got: Outcome | null = null;
    const other: string[] = [];
    try {
      const exit = await runCli(what, {
        onProcess: setProcess,
        onStep: (e) => setSteps((s) => [...s, e]),
        onTool: (e) => setSteps((s) => [...s, { event: "tool", step: e.step, words: toolWords(e) }]),
        onOutcome: (o) => { got = o; },
        onOther: (line) => other.push(line),
      });
      const stopped = got as Outcome | null;
      const id = stopped?.run_id ?? ("resume" in what ? what.resume.run_id : null);
      // The run as it stands, from this machine's run file: the history so far and the pause it waits at.
      if (id) {
        setRunId(id);
        try { setRecord(await localRun(id)); } catch { /* the outcome below still says where it stopped */ }
      }
      setOutcome(stopped);
      if (exit.cancelled) {
        setCancelled(true);
        setProblem(`Cancelled: aip stopped (${exit.signal ?? `exit ${exit.code}`}).`);
      } else if (!stopped) {
        const said = [exit.error, ...other, exit.stderr.trim()].filter(Boolean).join("\n");
        setProblem(`aip exited with ${exit.code ?? exit.signal} and printed no outcome${said ? `:\n${said}` : "."}`);
      }
    } catch (e) {
      setProblem(describe(e));
    } finally {
      setRunning(false);
      setProcess(null);
    }
  };

  const start = (inputs: Record<string, unknown>) => {
    setSteps([]);
    setRunId(null);
    setRecord(null);
    setRanAhead(ahead);
    void call(ahead ? { runah: { ref: reference ?? "", inputs, human, studio } } : { run: { ref: reference ?? "", inputs } });
  };
  // A run started ahead goes on ahead: the person's answers in, then runah's model again until the next human step.
  const resume = (answers?: unknown) => {
    if (runId) void call({ resume: { run_id: runId, answers, ...(ranAhead ? (studio ? { studio: true } : { runah: true }) : {}) } });
  };
  const reset = () => { setSteps([]); setOutcome(null); setRecord(null); setRunId(null); setProblem(null); setCancelled(false); };

  if (loadError) return <p className="error" role="alert">{loadError}</p>;
  if (!about) return <p className="muted">Loading {reference ?? "the folder"}…</p>;

  const failed = outcome !== null && "error" in outcome ? outcome : null;
  // The run file is the truth of where the run stands: an answer that was refused leaves it paused.
  const status: Status = running ? "running" : cancelled ? "cancelled"
    : record ? record.status
    : outcome === null ? (problem ? "failed" : "not started")
    : "paused" in outcome ? "paused" : "done" in outcome ? "done" : "failed";
  // Inputs the Start step refused opened no run: fix them and start again.
  const unstarted = !running && runId === null;
  const recorded = outcome?.recorded;

  return (
    <article className="run">
      <nav className="crumbs">
        {folder ? <><a href={href({ page: "catalog" })}>folder</a> <code>{consoleConfig().folder}</code> / run</> : (
          <><a href={href({ page: "catalog" })}>catalog</a> / <a href={href({ page: "procedure", ref: reference ?? about.name })}><code>{about.name}</code></a> / run</>
        )}
      </nav>
      <h1>{about.name} <span className="muted rev">{folder ? "local run" : about.revision ? `run @${about.revision}` : "run"}</span> <DraftBadge draft={record?.draft ?? (!folder && about.draft === true)} /></h1>
      <p className="run-meta">
        <span>status <strong data-testid="run-status" className={`run-${status}`}>{status}</strong></span>
        {runId && <span> · run <a href={href({ page: "run-detail", id: runId })}><code data-testid="run-id">{runId}</code></a></span>}
        {recorded !== undefined && <span data-testid="run-recorded" data-recorded={String(recorded)}> · {recorded ? "recorded" : "not recorded (the server did not take it)"}</span>}
        <span className="muted"> · aip {consoleConfig().aip.version} on this machine, in <code data-testid="run-workdir">{record?.workdir ?? consoleConfig().workdir}</code>, as agent <code data-testid="run-agent">{studio ? "studio" : "console"}</code>, session <code data-testid="session-id">{sessionId()}</code></span>
        {(steps.length > 0 || outcome) && !running && <> · <button type="button" onClick={reset}>new run</button></>}
      </p>

      <div className="run-grid">
        <div>
          {unstarted && agents !== null && (
            <HowToRun agents={agents} settings={settings} ahead={ahead} human={human} busy={running}
                      onAhead={setAhead} onHuman={setHuman} />
          )}
          {unstarted && (
            <KeysForm title="Inputs" testid="pause-start" submit="Start" busy={running} types={about.inputs}
                      descriptions={about.input_descriptions} initial={about.example_inputs} onSubmit={start}
                      intro={<p className="muted">What the <code>Start</code> step takes.</p>} />
          )}
          {failed && runId === null && <ErrorSummary error={failed} />}
          {running && (
            <section className="pause" data-testid="run-running">
              <p>aip is running{steps.length ? `; last step ${steps[steps.length - 1].step}` : ""}…</p>
              <div className="actions">
                <button type="button" disabled={!process} onClick={() => process && void cancelCli(process)}>Cancel</button>
              </div>
            </section>
          )}
          {problem && <pre className="error" role="alert" data-testid="run-problem">{problem}</pre>}
          {record && <RecordSummary record={record} />}
          {record && <RecordHistory record={record} />}
          {!running && failed && runId !== null && <ErrorSummary error={failed} runId={runId} />}
          {!running && record?.status === "paused" && record.pause && (
            <PauseForm key={`${record.history.length}-${record.pause.step}`} step={record.pause.step} tasks={record.pause.tasks}
                       refused={failed !== null} onAnswer={resume}
                       stopped={outcome !== null && "paused" in outcome ? (outcome as Paused).answerer ?? null : null} />
          )}
          {!running && runId !== null && ((failed && retryable(failed) && record?.status !== "paused") || cancelled) && (
            <div className="actions">
              <span className="muted">The run kept the state before the step it stopped at. Fix the cause, then retry it.</span>
              <button type="button" data-testid="retry" onClick={() => resume()}>Retry</button>
            </div>
          )}
          {!running && record?.status === "done" && (
            <section className="pause" data-testid="run-done">
              <h2>Done</h2>
              <p className="muted">The result: what the <code>End</code> step reads.</p>
              <Json value={record.result ?? {}} testid="run-result" />
            </section>
          )}
        </div>

        <aside>
          {record && (
            <>
              <h2>Path</h2>
              <p className="muted small">The run so far over the step graph: what it reached and the arrows it took are heavy.</p>
              <RunPath record={record} direction="down" />
            </>
          )}
          <h2>Steps</h2>
          <p className="muted small">One line per step as the CLI reports it (<code>--progress</code>), in the order things happened.</p>
          <ol className="trace small" data-testid="trace">
            {steps.map((s, i) => s.event === "tool" ? (
              <li key={i} data-step={s.step} data-kind="tool" className="muted">runah&apos;s model, at <code>{s.step}</code>: {s.words}</li>
            ) : (
              <li key={i} data-step={s.step} data-kind={s.kind}>
                <code>{s.step}</code> <span className="muted">{s.kind}</span>
                {passLabel(s.passes) && <span className="muted"> · {passLabel(s.passes)}</span>}
                {s.to && <> → <code data-testid="branch-taken">{s.to}</code></>}
                {s.fired && <span className="status-tag check-fired"> check fired</span>}
                {s.exit && <span className="muted"> exit: {s.exit}{s.iterations !== undefined ? `, ${s.iterations} passes` : ""}</span>}
                {s.seconds !== undefined && <span className="muted"> · {duration(s.seconds)}</span>}
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </article>
  );
}

const retryable = (error: Failed) => error.resumable === true;

/** How the run goes: `aip run`, every task pausing for this page; or `aip runah`, runah's model answering every task
 *  but those of the steps ticked here, the human steps, which pause for this page. The ticks start on the steps written
 *  for a person (run/human.ts). */
function HowToRun({ agents, settings, ahead, human, busy, onAhead, onHuman }: {
  agents: AgentStep[]; settings: ModelSettings | null; ahead: boolean; human: string[]; busy: boolean;
  onAhead: (ahead: boolean) => void; onHuman: (human: string[]) => void;
}) {
  const model = settings?.runah;
  const toggle = (name: string, on: boolean) => onHuman(on ? [...new Set([...human, name])] : human.filter((h) => h !== name));
  return (
    <section className="pause" data-testid="run-how" data-mode={ahead ? "runah" : "run"}>
      <h2>How it runs</h2>
      <div className="options" role="radiogroup" aria-label="how it runs">
        <label className="option">
          <input type="radio" name="run-how" checked={ahead} disabled={busy} data-testid="run-how-runah" onChange={() => onAhead(true)} />
          {" "}run ahead (<code>aip runah</code>): runah&apos;s model answers the tasks, a person answers the steps ticked below
        </label>
        <label className="option">
          <input type="radio" name="run-how" checked={!ahead} disabled={busy} data-testid="run-how-run" onChange={() => onAhead(false)} />
          {" "}run (<code>aip run</code>): every task pauses here for you
        </label>
      </div>
      {ahead && (
        <>
          <p className="muted small" data-testid="run-how-model">
            {model ? <>runah&apos;s model: <code>{model.model}</code> at <code>{model.endpoint}</code>{model.key ? "" : ", with no key set: set one in the Studio's Settings or with `aip config runah --model-key`"}</> : "runah's model: not known"}
          </p>
          {agents.length === 0
            ? <p className="muted small">It has no Task_Agent step: nothing for a model or a person to answer.</p>
            : (
              <fieldset className="human-steps" data-testid="human-steps">
                <legend>steps a person answers <span className="muted small">(<code>--human</code>): the run stops there for the form</span></legend>
                {agents.map((s) => (
                  <label key={s.name} className="option" data-testid="human-step" data-step={s.name} data-person={String(s.person)}>
                    <input type="checkbox" checked={human.includes(s.name)} disabled={busy} onChange={(e) => toggle(s.name, e.target.checked)} />
                    {" "}<code>{s.name}</code> <span className="muted small">{s.description.split("\n")[0]}</span>
                  </label>
                ))}
              </fieldset>
            )}
        </>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ the forms

interface KeysFormProps {
  title: string;
  testid: string;
  submit: string;
  intro?: ReactNode;
  /** The keys the object must hold, and their types. */
  types: Record<string, string | null>;
  labels?: Record<string, string[]>;
  descriptions?: Record<string, string>;
  initial?: Record<string, unknown>;
  busy: boolean;
  onSubmit: (value: Record<string, unknown>) => void;
}

/** One field per key, typed: a pick for an answer with labels or a true_or_false, text for a string, JSON for the
 *  rest. The CLI checks the object against the step, and says what it would not take. */
function KeysForm({ title, testid, submit, intro, types, labels = {}, descriptions = {}, initial = {}, busy, onSubmit }: KeysFormProps) {
  const [fields, setFields] = useState<Record<string, string>>(
    () => Object.fromEntries(Object.entries(types).map(([key, type]) => [key, fieldText(initial[key], type)])));
  const [problems, setProblems] = useState<Record<string, string>>({});

  const go = () => {
    const made = collect(fields, types, labels);
    setProblems(made.problems);
    if (Object.keys(made.problems).length === 0) onSubmit(made.value);
  };

  return (
    <section className="pause" data-testid={testid}>
      <h2>{title}</h2>
      {intro}
      <Fields prefix={testid} types={types} labels={labels} descriptions={descriptions} fields={fields} problems={problems} busy={busy}
              onChange={(key, value) => setFields((f) => ({ ...f, [key]: value }))} />
      <div className="actions">
        <button type="button" onClick={go} disabled={busy} data-testid={`${testid}-submit`}>{submit}</button>
      </div>
    </section>
  );
}

interface FieldsProps {
  prefix: string;
  types: Record<string, string | null>;
  labels: Record<string, string[]>;
  descriptions?: Record<string, string>;
  fields: Record<string, string>;
  problems: Record<string, string>;
  busy: boolean;
  onChange: (key: string, value: string) => void;
  /** For a `list` key, the rows the task carries to tick from (`candidatesOf`): a checklist instead of JSON. */
  candidates?: Record<string, unknown[]>;
}

const isYesNo = (type: string | null) => type === "true_or_false" || type === "boolean";

export function Fields({ prefix, types, labels, descriptions = {}, fields, problems, busy, onChange, candidates = {} }: FieldsProps) {
  return (
    <div className="fields">
      {Object.entries(types).map(([key, type]) => {
        const rows = candidates[key];
        const kind = rows ? "checklist" : fieldKind(type, labels[key]);
        const value = fields[key] ?? "";
        return (
          <div key={key} className="field" data-testid="field" data-key={key} data-kind={kind}>
            <span><code>{key}</code> <span className="muted small">{type ?? "any"}{descriptions[key] ? ` · ${descriptions[key]}` : ""}</span></span>
            {rows ? (
              <Checklist name={key} rows={rows} value={value} busy={busy} onChange={(v) => onChange(key, v)} />
            ) : kind === "pick" && isYesNo(type) && !(labels[key]?.length) ? (
              // A true_or_false is two buttons.
              <span className="options yes-no" role="radiogroup" aria-label={key}>
                {["true", "false"].map((option) => (
                  <button key={option} type="button" role="radio" aria-checked={value === option} disabled={busy}
                          className={value === option ? "chosen" : ""} onClick={() => onChange(key, option)}>{option}</button>
                ))}
              </span>
            ) : kind === "pick" ? (
              <span className="options">
                {optionsOf(type, labels[key]).map((option) => (
                  <label key={option} className="option">
                    <input type="radio" name={`${prefix}-${key}`} value={option} checked={value === option} disabled={busy}
                           onChange={() => onChange(key, option)} /> {option}
                  </label>
                ))}
              </span>
            ) : kind === "text" ? (
              <textarea rows={3} value={value} disabled={busy} aria-label={key} onChange={(e) => onChange(key, e.target.value)} />
            ) : kind === "number" ? (
              <input type="text" inputMode="decimal" value={value} disabled={busy} aria-label={key} onChange={(e) => onChange(key, e.target.value)} />
            ) : (
              <textarea className="json" rows={3} value={value} disabled={busy} aria-label={key} placeholder="JSON"
                        onChange={(e) => onChange(key, e.target.value)} />
            )}
            {problems[key] && <span className="error small" role="alert">{key}: {problems[key]}</span>}
          </div>
        );
      })}
    </div>
  );
}

/** A list answer ticked from the rows the task carries; the field's text is the JSON list of the rows ticked. */
function Checklist({ name, rows, value, busy, onChange }: { name: string; rows: unknown[]; value: string; busy: boolean; onChange: (v: string) => void }) {
  let picked: unknown[] = [];
  try { const v = JSON.parse(value || "[]"); if (Array.isArray(v)) picked = v; } catch { /* typed by hand: start from none */ }
  const has = (row: unknown) => picked.some((p) => JSON.stringify(p) === JSON.stringify(row));
  const set = (row: unknown, on: boolean) =>
    onChange(JSON.stringify(rows.filter((r) => (r === row ? on : has(r)))));
  return (
    <span className="options checklist" role="group" aria-label={name}>
      {rows.map((row, i) => (
        <label key={i} className="option" data-testid="checklist-row">
          <input type="checkbox" checked={has(row)} disabled={busy} onChange={(e) => set(row, e.target.checked)} /> {rowText(row)}
        </label>
      ))}
    </span>
  );
}

/** A pause: every task waiting at the step, each with its prompt, the state it reads and a field per key it
 *  answers with. Several tasks (the passes of a `For` batch) are answered together, in one resume. The form is
 *  built from the step's `Produce` fields; the answer as hand-typed JSON stays behind it. `stopped` says why runah
 *  stopped here, when it did. */
function PauseForm({ step, tasks, refused, onAnswer, stopped = null }: {
  step: string; tasks: Task[]; refused: boolean; onAnswer: (answers: unknown) => void; stopped?: Paused["answerer"] | null;
}) {
  const candidates = (task: Task) => Object.fromEntries(Object.entries(task.answer_with)
    .map(([key, type]) => [key, candidatesOf(type, task.state)] as const).filter(([, rows]) => rows !== null)) as Record<string, unknown[]>;
  // A checklist starts with nothing ticked: an empty list.
  const [fields, setFields] = useState<Record<number, Record<string, string>>>(
    () => Object.fromEntries(tasks.map((t) => [t.index, Object.fromEntries(Object.keys(candidates(t)).map((k) => [k, "[]"]))])));
  const [problems, setProblems] = useState<Record<number, Record<string, string>>>({});
  const [raw, setRaw] = useState("");
  const [rawProblem, setRawProblem] = useState<string | null>(null);
  const answerRaw = () => {
    try { setRawProblem(null); onAnswer(JSON.parse(raw)); } catch { setRawProblem("not JSON"); }
  };

  const go = () => {
    const byTask: Record<number, Record<string, unknown>> = {};
    const wrong: Record<number, Record<string, string>> = {};
    for (const task of tasks) {
      const made = collect(fields[task.index] ?? {}, task.answer_with, task.labels ?? {});
      byTask[task.index] = made.value;
      if (Object.keys(made.problems).length > 0) wrong[task.index] = made.problems;
    }
    setProblems(wrong);
    if (Object.keys(wrong).length === 0) onAnswer(answersFor(tasks, byTask));
  };

  return (
    <section className="pause" data-testid="pause-task" data-step={step} data-tasks={tasks.length}>
      <h2>Task at <code>{step}</code>{tasks.length > 1 ? `: ${tasks.length} tasks` : ""}</h2>
      {tasks.length > 1 && (
        <p className="muted" data-testid="batched-note">
          These are the passes of a loop that reached this step in one batch. They are answered together: one answer resumes them all.
        </p>
      )}
      {stopped && (
        <p className="muted small" data-testid="pause-why">{/human step/.test(stopped.reason) ? "A step for a person: runah stopped here for you." : `runah stopped here: ${stopped.reason}`}</p>
      )}
      {refused && <p className="error" role="alert" data-testid="answer-refused">The last answer was refused, nothing was applied, and the same tasks wait. Answer again.</p>}
      {tasks.map((task) => (
        <fieldset key={task.index} className="question" data-testid="task" data-index={task.index} data-pass={task.pass ?? ""}>
          <legend>
            task {task.index}{passLabel(task.passes) && <span className="muted"> · {passLabel(task.passes)}</span>}
            {task.last_pass && <span className="status-tag flagged" data-testid="last-pass" title="No pass follows this one: nothing will check this answer before the loop ends."> last pass of {task.pass_of}</span>}
          </legend>
          <pre className="task" data-testid="task-prompt">{task.prompt}</pre>
          {task.references.length > 0 && (
            <>
              <h4>references to read when the task calls for them</h4>
              <ul data-testid="references">
                {task.references.map((r) => <li key={r.path}><code>{r.path}</code>{r.description ? ` — ${r.description}` : ""}</li>)}
              </ul>
            </>
          )}
          <details className="states">
            <summary>state <span className="muted small">the keys the step reads</span></summary>
            <Json value={task.state} testid="pause-state" />
          </details>
          <Fields prefix={`task-${task.index}`} types={task.answer_with} labels={task.labels ?? {}} fields={fields[task.index] ?? {}}
                  problems={problems[task.index] ?? {}} busy={false} candidates={candidates(task)}
                  onChange={(key, value) => setFields((f) => ({ ...f, [task.index]: { ...(f[task.index] ?? {}), [key]: value } }))} />
        </fieldset>
      ))}
      <div className="actions">
        <button type="button" onClick={go} data-testid="answer">{tasks.length > 1 ? `Answer all ${tasks.length}` : "Answer"}</button>
      </div>
      <details className="answer-json" data-testid="answer-json">
        <summary className="small">answer as JSON <span className="muted">(as <code>aip resume --answers</code> takes it)</span></summary>
        <textarea className="json" rows={4} value={raw} aria-label="answers as JSON" placeholder={tasks.length > 1 ? '{"0": {...}, "1": {...}}' : "{...}"}
                  onChange={(e) => setRaw(e.target.value)} />
        <div className="actions">
          <button type="button" onClick={answerRaw} disabled={!raw.trim()} data-testid="answer-json-submit">Answer with this JSON</button>
          {rawProblem && <span className="error small" role="alert">{rawProblem}</span>}
        </div>
      </details>
    </section>
  );
}
