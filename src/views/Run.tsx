import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import {
  cancelCli, consoleConfig, isFolderMode, runCli, skillInfo,
  type Outcome, type Paused, type RunErrorObject, type SkillInfo, type StepEvent,
} from "../api/console";
import type { CatalogEntry } from "../api/types";
import { answerOf, asFieldText, coerce, optionsOf } from "../run/protocol";
import { href } from "../router";
import { describe } from "./Source";

/** View 3: the run console. Runs go through the `aip` CLI on this machine (`aip run --progress`, then
 *  `aip resume --progress` per answer), so scripts run here and decisions are resolved by this client. */
export function Run({ reference }: { reference?: string }) {
  if (isFolderMode()) return <Console key="folder" reference={consoleConfig().folder!} />;
  if (!reference) return <Picker />;
  return <Console key={reference} reference={reference} />;
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
      <ul className="picker">
        {entries.map((c) => (
          <li key={c.name}>
            {c.latest === null
              ? <><code className="muted">{c.name}</code><span className="muted"> — every revision is retired; nothing to run</span></>
              : <>
                  <a href={href({ page: "run", ref: c.name })}><code>{c.name}</code></a>
                  <span className="muted"> @{c.pinned ?? c.latest}{c.pinned ? " (pinned)" : ""} — {c.description}</span>
                </>}
          </li>
        ))}
      </ul>
    </article>
  );
}

// ------------------------------------------------------------------ the session

type Status = "not started" | "running" | "paused" | "done" | "failed" | "cancelled";

function Console({ reference }: { reference: string }) {
  const folder = isFolderMode();
  const [skill, setSkill] = useState<SkillInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [session, setSession] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    skillInfo(reference).then(setSkill).catch((e: unknown) => setLoadError(describe(e)));
  }, [reference]);

  const call = async (what: Parameters<typeof runCli>[0]) => {
    setRunning(true);
    setCancelled(false);
    setProblem(null);
    setOutcome(null);
    let got: Outcome | null = null;
    const other: string[] = [];
    try {
      const exit = await runCli(what, {
        onSession: setSession,
        onStep: (e) => setSteps((s) => [...s, e]),
        onOutcome: (o) => {
          got = o;
          setOutcome(o);
          if (o.run_id) setRunId(o.run_id);
        },
        onOther: (line) => other.push(line),
      });
      if (exit.cancelled) {
        setCancelled(true);
        setProblem(`Cancelled: aip stopped (${exit.signal ?? `exit ${exit.code}`}).`);
      } else if (!got) {
        const said = [exit.error, ...other, exit.stderr.trim()].filter(Boolean).join("\n");
        setProblem(`aip exited with ${exit.code ?? exit.signal} and printed no outcome${said ? `:\n${said}` : "."}`);
      }
    } catch (e) {
      setProblem(describe(e));
    } finally {
      setRunning(false);
      setSession(null);
    }
  };

  const start = (input: Record<string, unknown>) => {
    setSteps([]);
    setRunId(null);
    void call({ run: { ref: reference, input } });
  };
  const resume = (input?: Record<string, unknown>) => {
    if (runId) void call({ resume: { run_id: runId, input } });
  };
  const reset = () => { setSteps([]); setOutcome(null); setRunId(null); setProblem(null); setCancelled(false); };

  if (loadError) return <p className="error" role="alert">{loadError}</p>;
  if (!skill) return <p className="muted">Loading {reference}…</p>;

  const name = skill.info.meta.name;
  const status: Status = running ? "running" : cancelled ? "cancelled"
    : outcome === null ? (problem ? "failed" : "not started")
    : "paused" in outcome ? "paused" : "done" in outcome ? "done" : "failed";
  // A start input the first step rejected opened nothing: fix it and start again.
  const restart = outcome !== null && "error" in outcome && outcome.run_id === null;

  return (
    <article className="run">
      <nav className="crumbs">
        {folder ? <>folder <code>{consoleConfig().folder}</code> / run</> : (
          <><a href={href({ page: "catalog" })}>catalog</a> / <a href={href({ page: "procedure", ref: reference })}><code>{name}</code></a> / run</>
        )}
      </nav>
      <h1>{name} <span className="muted rev">{folder ? "local run" : reference.includes("@") ? `run @${reference.split("@")[1]}` : "run"}</span></h1>
      <p className="run-meta">
        <span>status <strong data-testid="run-status">{status}</strong></span>
        {runId && (
          <span> · run {folder ? <code data-testid="run-id">{runId}</code>
                                : <a href={href({ page: "run-detail", id: runId })}><code data-testid="run-id">{runId}</code></a>}</span>
        )}
        <span className="muted"> · aip {consoleConfig().aip.version} on this machine, in <code>{consoleConfig().workdir}</code></span>
        {(steps.length > 0 || outcome) && !running && <> · <button type="button" onClick={reset}>new run</button></>}
      </p>

      <div className="run-grid">
        <div>
          {(status === "not started" || restart || (status === "failed" && !runId)) && (
            <InputForm title={`Start input for ${skill.info.start.step}`} testid="pause-start" submit="Start"
                       expects={skill.info.start.inputs} initial={skill.example_input} busy={running} onSubmit={start} />
          )}
          {running && (
            <section className="pause" data-testid="run-running">
              <p>aip is running{steps.length ? `; last step ${steps[steps.length - 1].step}` : ""}…</p>
              <div className="actions">
                <button type="button" disabled={!session} onClick={() => session && void cancelCli(session)}>Cancel</button>
              </div>
            </section>
          )}
          {problem && <pre className="error" role="alert" data-testid="run-problem">{problem}</pre>}
          {cancelled && runId && (
            <div className="actions"><button type="button" onClick={() => resume()}>Retry</button></div>
          )}
          {!running && outcome && "paused" in outcome && <PauseView pause={outcome} onAnswer={resume} />}
          {!running && outcome && "error" in outcome && <ErrorView error={outcome} onRetry={() => resume()} />}
          {!running && outcome && "done" in outcome && (
            <section className="pause" data-testid="run-done">
              <h2>Done</h2>
              <p className="muted">The procedure's result: the end step's inputs.{!folder && runId && <> Every step is in the run's <a href={href({ page: "run-detail", id: runId })}>history</a>.</>}</p>
              <pre data-testid="final-state">{JSON.stringify(outcome.state, null, 2)}</pre>
            </section>
          )}
        </div>

        <aside>
          <h2>Steps</h2>
          <p className="muted small">One line per step the CLI reports as it completes (<code>--progress</code>).</p>
          <ol className="trace small" data-testid="trace">
            {steps.map((s, i) => (
              <li key={i} data-step={s.step} data-kind={s.kind}>
                <code>{s.step}</code> <span className="muted">{s.kind}</span>
                {s.to && <> → <code data-testid="branch-taken">{s.to}</code></>}
                {s.resolver && <span className="muted"> · {s.resolver}</span>}
                {s.seconds !== undefined && <span className="muted"> · {s.seconds}s</span>}
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </article>
  );
}

// ------------------------------------------------------------------ outcomes

function PauseView({ pause, onAnswer }: { pause: Paused; onAnswer: (input: Record<string, unknown>) => void }) {
  return (
    <>
      {pause.paused === "decision" && <DecisionForm pause={pause} onAnswer={onAnswer} />}
      {pause.paused === "client_task" && (
        <InputForm title={`Client task ${pause.step}`} testid="pause-client-task" submit="Answer"
                   intro={<>
                     <h3>task</h3>
                     <pre className="task" data-testid="task">{pause.task}</pre>
                     {pause.references.length > 0 && (
                       <>
                         <h3>references the client may load</h3>
                         <ul data-testid="references">
                           {pause.references.map((r) => <li key={r.uri}><code>{r.uri}</code> — {r.description}</li>)}
                         </ul>
                       </>
                     )}
                     <StateBlock state={pause.state} />
                     <p className="muted">Do the task and answer with its outputs.</p>
                   </>}
                   expects={pause.answer_with} initial={{}} busy={false} onSubmit={onAnswer} />
      )}
    </>
  );
}

function StateBlock({ state }: { state: Record<string, unknown> }) {
  return (
    <details className="states" open>
      <summary>state <span className="muted small">the step's declared inputs</span></summary>
      <pre data-testid="pause-state">{JSON.stringify(state, null, 2)}</pre>
    </details>
  );
}

function ErrorView({ error, onRetry }: { error: RunErrorObject; onRetry: () => void }) {
  return (
    <section className="pause error-box" data-testid="run-error" data-kind={error.error}>
      <h2><span data-testid="error-kind">{error.error}</span>{error.step && <> at <code>{error.step}</code></>}</h2>
      <p className="error" role="alert">{error.message}</p>
      {error.error === "no_decision_model" && (
        <p className="muted" data-testid="no-decision-model">
          This decision has <code>fallback: false</code>, so it is not answered by hand. Configure a decision model for the
          <code> aip</code> on this machine (<code>aip config --decision-model KEY</code>, or <code>TYPESAFE_API_KEY</code>), then retry: the run waits at the step.
        </p>
      )}
      {error.exit_code !== undefined && <p>exit code <code data-testid="exit-code">{error.exit_code}</code>{error.script && <> from <code>{error.script}</code></>}</p>}
      {error.stderr && <><h3>stderr</h3><pre data-testid="error-stderr">{error.stderr}</pre></>}
      {error.missing && error.missing.length > 0 && <p>missing {error.missing.map((m) => <code key={m}>{m} </code>)}</p>}
      {error.invalid && error.invalid.length > 0 && <p>invalid {error.invalid.map((m) => <code key={m}>{m} </code>)}</p>}
      <details>
        <summary>the error object</summary>
        <pre data-testid="error-object">{JSON.stringify(error, null, 2)}</pre>
      </details>
      {error.resumable && (
        <>
          <p className="muted">The run kept the state before this step. Fix the cause, then retry it.</p>
          <div className="actions"><button type="button" onClick={onRetry}>Retry</button></div>
        </>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ the forms

interface InputFormProps {
  title: string;
  testid: string;
  submit: string;
  intro?: React.ReactNode;
  /** Keys the answer must hold, with their types: a typed field each. */
  expects: Record<string, string>;
  initial: Record<string, unknown>;
  busy: boolean;
  onSubmit: (payload: Record<string, unknown>) => void;
}

/** An input or answer: typed fields for the expected keys, and the whole object as JSON (the source of truth). */
function InputForm({ title, testid, submit, intro, expects, initial, busy, onSubmit }: InputFormProps) {
  const [text, setText] = useState(() => JSON.stringify(withBlanks(initial, expects), null, 2));
  const [problem, setProblem] = useState<string | null>(null);

  const parsed = useMemo(() => {
    try {
      const v = JSON.parse(text);
      if (!v || typeof v !== "object" || Array.isArray(v)) return null;
      return v as Record<string, unknown>;
    } catch { return null; }
  }, [text]);

  const setKey = (key: string, raw: string, type: string) => {
    if (!parsed) return;
    try {
      setText(JSON.stringify({ ...parsed, [key]: coerce(raw, type) }, null, 2));
      setProblem(null);
    } catch (e) { setProblem(`${key}: ${(e as Error).message}`); }
  };

  const go = () => {
    if (!parsed) { setProblem("the payload must be a JSON object"); return; }
    setProblem(null);
    onSubmit(parsed);
  };

  return (
    <section className="pause" data-testid={testid}>
      <h2>{title}</h2>
      {intro}
      {Object.keys(expects).length > 0 && (
        <div className="fields">
          {Object.entries(expects).map(([key, type]) => (
            <label key={key} className="field">
              <span><code>{key}</code> <span className="muted small">{type}</span></span>
              {type === "boolean" ? (
                <input type="checkbox" checked={parsed?.[key] === true} disabled={!parsed || busy}
                       onChange={(e) => setKey(key, String(e.target.checked), type)} aria-label={key} />
              ) : type === "string" ? (
                <textarea rows={3} value={parsed ? asFieldText(parsed[key], type) : ""} disabled={!parsed || busy}
                          onChange={(e) => setKey(key, e.target.value, type)} aria-label={key} />
              ) : (
                <input type="text" value={parsed ? asFieldText(parsed[key], type) : ""} disabled={!parsed || busy}
                       onChange={(e) => setKey(key, e.target.value, type)} aria-label={key} />
              )}
            </label>
          ))}
        </div>
      )}
      <label className="field">
        <span>payload <span className="muted small">JSON; the CLI checks it against the step</span></span>
        <textarea className="json" rows={Math.min(16, text.split("\n").length + 1)} value={text} data-testid="payload"
                  aria-label="payload" disabled={busy} onChange={(e) => { setText(e.target.value); setProblem(null); }} />
      </label>
      {!parsed && <p className="error small">Not a JSON object.</p>}
      {problem && <p className="error small" role="alert">{problem}</p>}
      <div className="actions">
        <button type="button" onClick={go} disabled={busy || !parsed}>{submit}</button>
      </div>
    </section>
  );
}

function withBlanks(initial: Record<string, unknown>, expects: Record<string, string>): Record<string, unknown> {
  const out = { ...initial };
  for (const [k, t] of Object.entries(expects)) {
    if (!(k in out)) out[k] = t === "object" ? {} : t.startsWith("list") ? [] : t === "boolean" ? false : t === "string" ? "" : 0;
  }
  return out;
}

/** A decision this client has no model for: answer each question (the CLI's `--interactive` prompts). */
function DecisionForm({ pause, onAnswer }: { pause: Extract<Paused, { paused: "decision" }>; onAnswer: (a: Record<string, unknown>) => void }) {
  const questions = Object.entries(pause.questions);
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);

  const submit = () => {
    const answers: Record<string, unknown> = {};
    for (const [name, q] of questions) {
      const v = picked[name];
      if (v === undefined) { setProblem(`answer ${name}`); return; }
      answers[name] = answerOf(q.type, v);
    }
    setProblem(null);
    onAnswer(answers);
  };

  return (
    <section className="pause" data-testid="pause-decision">
      <h2>Decision {pause.step}: answer its questions</h2>
      <p className="muted">
        This client has no decision model (<code>aip config --decision-model</code>) and the step allows a manual answer
        (<code>fallback: true</code>), so the answers are yours; the run records them as <code>resolver: manual</code> with no confidence.
      </p>
      {pause.confidence?.length > 0 && (
        <p className="muted small" data-testid="manual-confidence-note">
          A model would also write {pause.confidence.map((q, i) => <span key={q}>{i ? ", " : ""}<code>{q}_confidence</code></span>)} to the state;
          a manual answer writes none, so a router that checks it fires with reason <code>absent</code>.
        </p>
      )}
      <StateBlock state={pause.state} />
      {questions.map(([name, q]) => (
        <fieldset key={name} className="question">
          <legend><code>{name}</code> <span className="muted small">{q.type}</span></legend>
          <p>{q.instructions}</p>
          {optionsOf(q).map(([value, label]) => (
            <label key={value} className="option">
              <input type="radio" name={`q-${pause.step}-${name}`} value={value} checked={picked[name] === value}
                     onChange={() => setPicked({ ...picked, [name]: value })} />
              {" "}{label}
            </label>
          ))}
        </fieldset>
      ))}
      {problem && <p className="error small" role="alert">{problem}</p>}
      <div className="actions">
        <button type="button" onClick={submit}>Answer</button>
      </div>
    </section>
  );
}
