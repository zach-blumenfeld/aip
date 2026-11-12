// A run's record, read: who ran it, where its time went, and its history with every loop's passes
// nested under the loop. The questions a reader of the raw JSON could not answer at a glance are the
// ones each row answers in words: how long the step took, who answered a task, where a route went and
// why, why a pass ran and why the loop ended. Used by the history page (a run the server holds) and
// by the run page (the run as it stands at each stop).

import type { ReactNode } from "react";
import type { AnswerObject, HistoryEntry, Resolution, RunErrorBody, RunRecord } from "../api/types";
import { href } from "../router";
import { duration, exitText, nest, timing, untilText, type LoopRows, type Row } from "../record/model.ts";
import { passLabel } from "../run/answers.ts";

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function DraftBadge({ draft }: { draft: boolean | undefined }) {
  return draft ? <span className="status-tag draft" data-testid="draft-badge" title="The bundle this ran has no revision: it was run from a folder or a file and is held as a draft.">draft</span> : null;
}

export function Json({ value, testid }: { value: unknown; testid?: string }) {
  return <pre data-testid={testid}>{JSON.stringify(value, null, 2)}</pre>;
}

const isAnswer = (v: unknown): v is AnswerObject => typeof v === "object" && v !== null && !Array.isArray(v) && "value" in v;

const percent = (p: number | null | undefined) => (p === null || p === undefined ? "—" : p.toFixed(2));

/** The run's facts above its history. */
export function RecordSummary({ record }: { record: RunRecord }) {
  const spent = timing(record.history);
  const total = record.started && record.finished ? (new Date(record.finished).getTime() - new Date(record.started).getTime()) / 1000 : null;
  return (
    <dl className="record-summary" data-testid="record-summary">
      <dt>who</dt>
      <dd>
        agent <code data-testid="run-agent">{record.identity?.agent ?? "—"}</code> · session <code data-testid="run-session">{record.identity?.session ?? "—"}</code>
        {" "}· user <code data-testid="run-user">{record.identity?.user ?? "—"}</code>
      </dd>
      <dt>when</dt>
      <dd>started {when(record.started)}{record.finished ? <> · finished {when(record.finished)}</> : null}</dd>
      <dt>time</dt>
      <dd data-testid="run-timing">
        {total !== null && <>{duration(total)} start to finish · </>}
        steps {duration(spent.steps) || "0 ms"} · the model {duration(spent.model) || "0 ms"} · waiting on agents {duration(spent.waited) || "0 ms"}
      </dd>
      <dt>bundle</dt>
      <dd><code title={record.bundle_id}>{record.bundle_id.slice(0, 12)}</code> <DraftBadge draft={record.draft} /></dd>
      {record.parent && (
        <>
          <dt>started by</dt>
          <dd data-testid="run-parent">
            run <a href={href({ page: "run-detail", id: record.parent.run_id })}><code>{record.parent.run_id}</code></a> at{" "}
            <code>{record.parent.step ?? "?"}</code>{record.parent.pass !== null && record.parent.pass !== undefined && <> pass {record.parent.pass}</>}
            <span className="muted"> · depth {record.depth ?? 1}</span>
          </dd>
        </>
      )}
      {(record.tokens || record.budget_tokens !== undefined) && (
        <>
          <dt>tokens</dt>
          <dd data-testid="run-tokens">
            {record.tokens?.total ?? 0} spent by runah's model ({record.tokens?.own ?? 0} in this run, {record.tokens?.children ?? 0} in the runs it started)
            {record.budget_tokens !== undefined && <> · budget {record.budget_tokens}</>}
          </dd>
        </>
      )}
      {record.children && record.children.length > 0 && (
        <>
          <dt>started</dt>
          <dd>
            <ul className="children" data-testid="run-children">
              {record.children.map((child) => (
                <li key={child.run_id} data-testid="run-child" data-run={child.run_id} data-status={child.status}>
                  <a href={href({ page: "run-detail", id: child.run_id })}><code>{child.run_id}</code></a> <code>{child.name ?? "?"}</code>{" "}
                  <DraftBadge draft={child.draft} /> <span className={`status-tag ${child.status}`}>{child.status}</span>
                  <span className="muted"> · from <code>{child.step ?? "?"}</code>{child.pass !== null && child.pass !== undefined && <> pass {child.pass}</>}
                  {child.tokens ? <> · {child.tokens} tokens</> : null}</span>
                </li>
              ))}
            </ul>
          </dd>
        </>
      )}
    </dl>
  );
}

/** The history, nested. */
export function RecordHistory({ record }: { record: RunRecord }) {
  const rows = nest(record.history);
  if (rows.length === 0) return <p className="muted">This run has no history yet.</p>;
  return <div className="record" data-testid="record">{rows.map((row, i) => <RowView key={i} row={row} />)}</div>;
}

function RowView({ row }: { row: Row }) {
  return row.type === "loop" ? <LoopView loop={row} /> : <EntryView entry={row.entry} seq={row.seq} />;
}

function LoopView({ loop }: { loop: LoopRows }) {
  const iterations = loop.entry?.result?.iterations;
  const count = typeof iterations === "number" ? iterations : loop.passes.length;
  return (
    <section className={`record-loop${loop.exit?.reason === "cap" ? " capped" : ""}`} data-testid="record-loop" data-loop={loop.name}
             data-exit={loop.exit?.reason ?? "open"} data-passes={loop.passes.length}>
      <h3>
        <span className="kind-tag loop">{loop.kind ?? "loop"}</span> <code>{loop.name}</code>{" "}
        {loop.exit
          ? <span className="loop-exit" data-testid="loop-exit">ended: {exitText(loop.exit, count)}</span>
          : <span className="loop-exit muted" data-testid="loop-exit">the run is inside it</span>}
      </h3>
      {loop.exit?.resolution && <p className="muted small">{resolutionText(loop.exit.resolution)}</p>}
      {loop.passes.length === 0 && <p className="muted small">No pass ran.</p>}
      {loop.passes.map((pass) => (
        <div key={pass.pass} className="record-pass" data-testid="record-pass" data-pass={pass.pass}>
          <h4>
            pass {pass.pass}
            {pass.until && <span className="muted until" data-testid="until" data-holds={String(pass.until.holds)}> · {untilText(pass.until)}</span>}
          </h4>
          {pass.rows.map((row, i) => <RowView key={i} row={row} />)}
        </div>
      ))}
      {loop.entry && Object.keys(loop.entry.result ?? {}).some((k) => k !== "iterations") && (
        <details className="states">
          <summary>what the loop collected</summary>
          <Json value={loop.entry.result} />
        </details>
      )}
    </section>
  );
}

function resolutionText(r: Resolution): string {
  const name = r.answer ?? r.source ?? "the answer";
  const bar = r.barred ? `, barred at probability ${percent(r.probability)}` : r.probability !== null && r.probability !== undefined ? ` (probability ${percent(r.probability)})` : "";
  return `${name} was ${JSON.stringify(r.value)}${bar}: ${r.holds ? "holds" : "does not hold"}`;
}

/** A task whose answering work is on record: `observed` when runah's model answered it (which model, the tool calls it
 *  made, counted by tool and then one by one, the tokens it spent and the answers refused before one held), `reported`
 *  when the agent that answered said what it spent (`aip resume --work`): its model if it gave one, its tool calls as a
 *  count or a list, its tokens, its time. */
function WorkAnswer({ entry }: { entry: HistoryEntry }) {
  const by = entry.answered_by;
  const listed = Array.isArray(entry.tool_calls) ? entry.tool_calls : [];
  const count = typeof entry.tool_calls === "number" ? entry.tool_calls : Array.isArray(entry.tool_calls) ? listed.length : null;
  const counts = new Map<string, number>();
  for (const c of listed) counts.set(c.name, (counts.get(c.name) ?? 0) + 1);
  const reported = entry.work === "reported";
  const calls = count === null ? null : <>{count} tool call{count === 1 ? "" : "s"}{counts.size > 0 && <> ({[...counts].map(([n, k]) => `${n} ${k}`).join(", ")})</>}</>;
  const spent = [
    calls,
    entry.tokens ? <>{entry.tokens.total} tokens</> : null,
    reported && entry.work_seconds !== undefined ? <>{duration(entry.work_seconds) || "0 ms"}</> : null,
  ].filter((x) => x !== null);
  return (
    <div data-testid="answered-by" data-agent={by?.agent ?? ""} data-session={by?.session ?? ""} data-model={by?.model ?? ""}
         data-work={entry.work ?? ""} data-tool-calls={count ?? ""}>
      <p>
        answered by <code>{by?.agent ?? "?"}</code>{by?.model && <> (<code>{by.model}</code>)</>}, {reported ? "reported" : "observed"}:{" "}
        {spent.length ? spent.map((s, i) => <span key={i}>{i ? ", " : ""}{s}</span>) : <span className="muted">nothing said</span>}
        {entry.refusals ? <>, after {entry.refusals} refused answer{entry.refusals === 1 ? "" : "s"}</> : null}; it produced {keyList(entry.result)}
      </p>
      {listed.length > 0 && (
        <details className="states">
          <summary>its tool calls</summary>
          <ol className="tool-calls" data-testid="tool-calls">
            {listed.map((c, i) => (
              <li key={i} data-tool={c.name}><code>{c.name}</code> {c.args ?? ""}{c.error && <span className="error small"> · {c.error}</span>}</li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

/** One step's entry: the line that says what happened, then what it read and produced. */
function EntryView({ entry, seq }: { entry: HistoryEntry; seq: number }) {
  const passes = passLabel(entry.passes);
  return (
    <section className={`step-card kind-${entry.kind}`} data-testid="record-entry" data-step={entry.step} data-kind={entry.kind}
             data-seq={seq} data-pass={entry.pass ?? ""}>
      <h3>
        <span className="kind-tag">{entry.kind}</span> <code>{entry.step}</code>
        {passes && <span className="muted small" data-testid="entry-pass"> · {passes}</span>}
        <span className="entry-time" data-testid="entry-time" title={`written ${entry.at}`}>
          {entry.seconds !== undefined ? `+${duration(entry.seconds)}` : ""}
        </span>
      </h3>
      <div className="entry-what" data-testid="entry-what">{what(entry)}</div>
      <details className="states">
        <summary>read and produced</summary>
        <div className="io-pair">
          <div><h4>read</h4><Json value={entry.input} testid="entry-input" /></div>
          <div><h4>produced</h4><Json value={entry.result} testid="entry-result" /></div>
        </div>
        {entry.prompt !== undefined && <><h4>the task as handed over</h4><pre className="task">{entry.prompt}</pre></>}
        {entry.stdin !== undefined && <><h4>the script's stdin</h4><Json value={entry.stdin} /></>}
      </details>
    </section>
  );
}

function AnswerRow({ name, value }: { name: string; value: unknown }) {
  if (!isAnswer(value)) return <tr><td><code>{name}</code></td><td colSpan={3}><code>{short(value)}</code></td></tr>;
  const probabilities = value.probabilities ? Object.entries(value.probabilities) : [];
  return (
    <tr data-testid="answer" data-name={name} data-value={String(value.value)}>
      <td><code>{name}</code></td>
      <td><strong>{String(value.value)}</strong></td>
      <td data-testid="answer-confidence">{value.confidence !== undefined ? `confidence ${percent(value.confidence)}` : <span className="muted">no confidence</span>}</td>
      <td>
        {probabilities.length > 0 && (
          <ul className="dist">
            {probabilities.map(([label, p]) => (
              <li key={label} className={label === String(value.value) ? "chosen" : undefined}>
                <span className="bar" style={{ width: `${Math.round(p * 100)}%` }} /><code>{label}</code> {percent(p)}
              </li>
            ))}
          </ul>
        )}
        {value.score !== undefined && <span className="muted small"> expected {value.score.toFixed(2)}</span>}
      </td>
    </tr>
  );
}

function short(value: unknown, limit = 160): string {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text === undefined ? "" : text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function keyList(o: Record<string, unknown> | undefined): ReactNode {
  const keys = Object.keys(o ?? {});
  if (keys.length === 0) return <span className="muted">nothing</span>;
  return keys.map((k, i) => <span key={k}>{i ? ", " : ""}<code>{k}</code></span>);
}

/** What happened at the step, in the terms of its kind. */
function what(entry: HistoryEntry): ReactNode {
  switch (entry.kind) {
    case "Start":
      return <>the run's inputs: {keyList(entry.input)}</>;
    case "End":
      return <>the result: {keyList(entry.result)}</>;
    case "Decide": {
      const by = entry.answered_by;
      return (
        <>
          <p data-testid="answered-by" data-model={by?.model ?? ""}>
            answered by the decision model <code>{by?.model ?? "?"}</code>{by?.endpoint && <span className="muted"> at {by.endpoint}</span>}
            {entry.model_seconds !== undefined && <> · the call took {duration(entry.model_seconds) || "0 ms"}</>}
            {entry.batched && <span data-testid="batched"> · one call for {entry.batch_size} passes</span>}
            {entry.history_sent && <> · the history was sent</>}
          </p>
          <table className="compact answers"><tbody>
            {Object.entries(entry.result ?? {}).map(([name, value]) => <AnswerRow key={name} name={name} value={value} />)}
          </tbody></table>
        </>
      );
    }
    case "Route": {
      const check = entry.check;
      return (
        <>
          <p>
            read <code>{entry.read ?? "?"}</code>{" "}
            {entry.value !== null && entry.value !== undefined
              ? <>which was <strong data-testid="route-value">{entry.value}</strong>, </>
              : null}
            went to <code data-testid="route-to">{entry.to ?? "?"}</code>
            {check?.fired && <> because its check fired</>}
          </p>
          {check && (
            <p className="check" data-testid="check" data-fired={String(check.fired)} data-reason={check.reason ?? ""}>
              <span className={`status-tag ${check.fired ? "check-fired" : "check-held"}`}>{check.fired ? "check fired" : "check passed"}</span>{" "}
              {check.confidence === null || check.confidence === undefined
                ? <>the answer carried no confidence, and the route asks for at least {check.below}</>
                : <>confidence {percent(check.confidence)} is {check.fired ? "below" : "not below"} {check.below}</>}
            </p>
          )}
          {!check && <p className="muted small">The route has no confidence check: the value alone decided.</p>}
        </>
      );
    }
    case "Aggregate":
      return (
        <table className="compact answers"><tbody>
          {Object.entries(entry.result ?? {}).map(([name, value]) => {
            const judged = entry.resolutions?.[name] ?? [];
            const barred = judged.filter((r) => r.barred).length;
            return (
              <tr key={name} data-testid="aggregation" data-name={name} data-value={isAnswer(value) ? String(value.value) : ""}>
                <td><code>{name}</code></td>
                <td><strong>{isAnswer(value) ? String(value.value) : short(value)}</strong> <span className="muted small">no confidence: an aggregation has none</span></td>
                <td>
                  {judged.length} {judged.length === 1 ? "answer" : "answers"} judged, {judged.filter((r) => r.holds).length} held
                  {barred > 0 && <span data-testid="barred">, {barred} turned by the confidence bar</span>}
                  <ul className="resolutions">
                    {judged.map((r, i) => <li key={i} className={r.holds ? undefined : "fails"}>{resolutionText(r)}</li>)}
                  </ul>
                </td>
              </tr>
            );
          })}
        </tbody></table>
      );
    case "Execute":
      return <>ran <code data-testid="script">{entry.script ?? "?"}</code> on this machine; it produced {keyList(entry.result)}</>;
    case "Task_Agent": {
      const by = entry.answered_by;
      if (entry.work) return <WorkAnswer entry={entry} />;
      return (
        <p data-testid="answered-by" data-agent={by?.agent ?? ""} data-session={by?.session ?? ""}>
          answered by agent <code>{by?.agent ?? "?"}</code>{by?.session && <> in session <code>{by.session}</code></>}
          {entry.waited_seconds !== undefined && <> after {duration(entry.waited_seconds) || "0 ms"}</>}; it produced {keyList(entry.result)}
        </p>
      );
    }
    default:
      return null;
  }
}

/** Where a paused run waits, read-only: the page that answers it is the run console. */
export function PauseSummary({ record }: { record: RunRecord }) {
  const pause = record.pause;
  if (!pause) return null;
  return (
    <section className="pause" data-testid="run-pause" data-step={pause.step} data-tasks={pause.tasks.length}>
      <h2>Paused at <code>{pause.step}</code></h2>
      <p>
        {pause.tasks.length === 1 ? "One task waits" : `${pause.tasks.length} tasks wait together`} for the agent{pause.since ? <>, since {when(pause.since)}</> : null}.
        {pause.tasks.length > 1 && <> They are the passes of a loop that reached this step in one batch, and one answer resumes them all.</>}
      </p>
      <ul>
        {pause.tasks.map((task) => (
          <li key={task.index} data-testid="waiting-task" data-index={task.index}>
            task {task.index}{passLabel(task.passes) && <span className="muted"> · {passLabel(task.passes)}</span>}: answer with {keyList(task.answer_with)}
            {task.last_pass && <span className="status-tag flagged" data-testid="last-pass"> last pass of {task.pass_of}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ErrorSummary({ error, runId }: { error: RunErrorBody; runId?: string | null }) {
  return (
    <section className="pause error-box" data-testid="run-error" data-kind={error.error}>
      <h2><span data-testid="error-kind">{error.error}</span>{error.step && <> at <code>{error.step}</code></>}{error.loop && <> in <code>{error.loop}</code></>}</h2>
      <p className="error" role="alert">{error.message}</p>
      {error.exit_code !== undefined && <p>exit code <code data-testid="exit-code">{error.exit_code}</code>{error.script && <> from <code>{error.script}</code></>}</p>}
      {error.stderr && <><h3>stderr</h3><pre data-testid="error-stderr">{error.stderr}</pre></>}
      {error.missing && error.missing.length > 0 && <p>missing {error.missing.map((m) => <code key={m}>{m} </code>)}</p>}
      {error.invalid && error.invalid.length > 0 && <p>invalid {error.invalid.map((m) => <code key={m}>{m} </code>)}</p>}
      {error.error === "loop_cap" && <p className="muted">A loop at its cap is not retried: the same passes would fail the same way. Run the procedure again.</p>}
      {error.error === "no_decision_model" && (
        <p className="muted" data-testid="no-decision-model">
          A <code>Decide</code> is always answered by a decision model. Configure one for the <code>aip</code> on the machine that runs
          (<code>aip config --decision-model-key KEY</code>){runId ? <>, then <code>aip resume {runId}</code> asks it</> : null}.
        </p>
      )}
    </section>
  );
}
