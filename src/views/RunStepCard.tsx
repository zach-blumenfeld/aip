import type { Attribution, CheckOutcome, ClientTaskResult, DecisionResult, HistoryEntry, ProcedureInfo } from "../api/types";
import { confidenceKey, inputsOf, outputsOf } from "../graph/dataflow";
import { href } from "../router";

interface Props {
  entry: HistoryEntry;
  info: ProcedureInfo;
  index: number;
}

type State = Record<string, unknown>;

/** One step of a recorded run: the declared keys it read and added, what it did, and where it ran. Read-only. */
export function RunStepCard({ entry, info, index }: Props) {
  const kind = entry.kind === "error" ? entry.step_kind ?? "error" : entry.kind;
  const io = stateIO(entry, info);
  return (
    <section className={`step-card run-card kind-${kind}`} data-testid="run-step" data-step={entry.step} data-kind={entry.kind}>
      <h3>
        <span className="muted">{index}. </span><code>{entry.step}</code> <span className="kind-tag">{kind}</span>
        {entry.kind === "error" && <span className="error"> · failed</span>}
      </h3>
      <Machine entry={entry} />
      {entry.kind === "start" && <p className="muted" data-testid="start-input">The start input the client gave: the procedure's inputs, as the run began.</p>}
      {entry.kind === "decision" && <Decision step={entry.step} result={entry.result as unknown as DecisionResult} info={info} attribution={entry.attribution} />}
      {entry.kind === "router" && <Router entry={entry} info={info} />}
      {entry.kind === "execution" && <Execution entry={entry} info={info} />}
      {entry.kind === "client_task" && <ClientTask result={entry.result as unknown as ClientTaskResult} info={info} />}
      {entry.kind === "end" && <pre data-testid="final-state">{JSON.stringify(entry.result, null, 2)}</pre>}
      {entry.kind === "error" && <ErrorResult result={entry.result} />}
      <div className="state-pair state-io">
        <div>
          <h4>state in <span className="muted small">{io.inLabel}</span></h4>
          <pre data-testid="state-in">{JSON.stringify(io.in, null, 2)}</pre>
        </div>
        <div>
          <h4>state out <span className="muted small">{io.outNote}</span></h4>
          {io.out && <pre data-testid="state-out">{JSON.stringify(io.out, null, 2)}</pre>}
        </div>
      </div>
    </section>
  );
}

/** Where a step ran. Scripts, decisions and tasks run on the client; the server only routes, checks and records. */
function Machine({ entry }: { entry: HistoryEntry }) {
  const kind = entry.kind === "error" ? entry.step_kind : entry.kind;
  const host = entry.kind === "error" ? (typeof entry.result.host === "string" ? entry.result.host : undefined) : entry.host;
  let where: "client" | "server" = "client";
  let text: React.ReactNode;
  if (kind === "execution") {
    text = <>ran on the client{host ? <> <code data-testid="host">{host}</code></> : ""}{entry.kind === "execution" && entry.seconds !== undefined ? ` in ${entry.seconds}s` : ""}</>;
  } else if (kind === "decision") {
    const who = entry.attribution;
    text = who?.resolver === "typesafe" ? <>answered on the client by its decision model{who.model ? <> <code>{who.model}</code></> : ""}</> : "answered on the client, by hand";
  } else if (kind === "client_task") {
    text = "performed by the client";
  } else {
    where = "server";
    text = kind === "router" ? "routed by the server" : kind === "end" ? "closed by the server" : kind === "start" ? "opened by the server with the client's input" : "recorded by the server";
  }
  return <p className="muted machine" data-testid="ran-on" data-machine={where} data-host={host}>{text}</p>;
}

/** The confidence keys a decision wrote to the state, from its attribution: `<question>_confidence` for each question
 *  the step emits one for. A manual answer wrote none. */
function confidenceOut(step: string, info: ProcedureInfo, attribution: Attribution | undefined): State {
  const out: State = {};
  const scores = attribution?.confidence;
  if (!scores) return out;
  for (const q of info.questions) if (q.step === step && q.confidence && scores[q.name] !== undefined) out[confidenceKey(q.name)] = scores[q.name];
  return out;
}

/** The declared keys a step read and added. A step sees only its `inputs`, so the history's `input` is the state
 *  in (an error entry keeps the whole state before the step: projected here). Out is the step's outputs: the
 *  start input, a script's stdout, a decision's answers and the confidence keys it emits, a client task's answer;
 *  routers and the end step add nothing. */
function stateIO(entry: HistoryEntry, info: ProcedureInfo) {
  const step = entry.step;
  const inKeys = inputsOf(info, step);
  const pick = (state: State, keys: string[]) => Object.fromEntries(keys.filter((k) => k in state).map((k) => [k, state[k]]));
  const input = entry.kind === "error" ? pick(entry.input, inKeys) : entry.input;
  const outKeys = outputsOf(info, step);
  let out: State | null = null;
  let outNote = outKeys.join(", ");
  if (entry.kind === "start") out = entry.input;
  else if (entry.kind === "execution") out = entry.result;
  else if (entry.kind === "decision") out = { ...(entry.result as unknown as DecisionResult).answers, ...confidenceOut(step, info, entry.attribution) };
  else if (entry.kind === "client_task") out = (entry.result as unknown as ClientTaskResult).answer;
  else if (entry.kind === "router") outNote = "adds nothing; the branch is in the history";
  else if (entry.kind === "end") outNote = "the procedure's result";
  else if (entry.kind === "error") outNote = "nothing: the step failed";
  if (entry.kind === "end") out = entry.result;
  const inLabel = entry.kind === "start" ? "nothing: the client's input opens the run" : inKeys.length ? inKeys.join(", ") : "no keys";
  return { in: input, inKeys, inLabel, out, outNote };
}

function Decision({ step, result, info, attribution }: { step: string; result: DecisionResult; info: ProcedureInfo; attribution?: Attribution }) {
  const byName = new Map(info.questions.filter((q) => q.step === step).map((q) => [q.name, q]));
  const who: Attribution = attribution ?? { resolver: "manual", model: null, confidence: null };
  const detail = info.step_details.find((s) => s.name === step);
  return (
    <>
      <p data-testid="attribution" data-resolver={who.resolver}>
        resolver <strong>{who.resolver}</strong>
        {who.resolver === "manual"
          ? <span className="muted"> · answered by the client, no decision model{detail?.fallback ? " (the step allows it: fallback on)" : ""}; no confidence recorded</span>
          : <span className="muted">{who.model ? ` · model ${who.model}` : ""}</span>}
      </p>
      <table className="compact answers" aria-label="answers">
        <thead><tr><th>question</th><th>answer</th><th>confidence</th><th>in the state</th></tr></thead>
        <tbody>
          {Object.entries(result.answers).map(([name, value]) => {
            const q = byName.get(name);
            const score = who.confidence?.[name];
            return (
              <tr key={name} data-testid="answer" data-question={name}>
                <td><code>{name}</code><div className="muted small">{q?.instructions}</div></td>
                <td><code data-testid="answer-value">{JSON.stringify(value)}</code></td>
                <td data-testid="answer-confidence">{score !== undefined ? score.toFixed(3) : <span className="muted">none{who.resolver === "manual" ? " (by hand)" : ""}</span>}</td>
                <td className="muted small">
                  {q?.confidence
                    ? (score !== undefined ? <><code>{confidenceKey(name)}</code> = {score.toFixed(3)}</> : <><code>{confidenceKey(name)}</code> not written</>)
                    : "answer only"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

const REASONS: Record<string, string> = {
  low: "the confidence was below the bound",
  absent: "no confidence was in the state (the decision was answered by hand)",
  null: "the confidence was null",
};

/** A router's entry: the branch key it read and where it went; with a check, the key it checked and whether the
 *  check fired, and why. */
function Router({ entry, info }: { entry: HistoryEntry; info: ProcedureInfo }) {
  const detail = info.step_details.find((s) => s.name === entry.step);
  const key = detail?.branch_on ?? Object.keys(entry.input)[0] ?? "?";
  const check = detail?.check ?? null;
  const outcome = (entry.result.confidence as CheckOutcome | undefined) ?? null;
  // A fired check decides before the branch key is read, so the entry records only the key it checked.
  return (
    <>
      <p data-testid="branch-taken">
        {key in entry.input && <><code>{key}</code> = <code>{JSON.stringify(entry.input[key])}</code> → </>}
        {outcome?.fired ? "the check sent the run to" : "branch to"} <code>{String(entry.result.to)}</code>
      </p>
      {check && (
        <p className="small" data-testid="check-outcome" data-fired={outcome?.fired ? "true" : "false"} data-reason={outcome?.reason ?? undefined}>
          <span className={`status-tag ${outcome?.fired ? "check-fired" : "check-held"}`}>{outcome?.fired ? "check fired" : "check held"}</span>{" "}
          <code>{check.key}</code> = <code>{JSON.stringify(entry.input[check.key] ?? null)}</code>, bound <code>{check.below}</code>
          {outcome?.fired && outcome.reason && <>: {REASONS[outcome.reason] ?? outcome.reason}</>}
          {!outcome?.fired && <>: at or above the bound, so the branches decided</>}
        </p>
      )}
    </>
  );
}

function Execution({ entry, info }: { entry: HistoryEntry; info: ProcedureInfo }) {
  const step = info.step_details.find((s) => s.name === entry.step);
  const assets = info.resources.filter((r) => r.step === entry.step && r.role === "asset").map((r) => r.path);
  return (
    <div className="io-pair">
      <div>
        <h4>stdin <span className="muted small">state{assets.length ? `, assets ${assets.map((a) => a.replace(/^.*\//, "").replace(/\.[^.]+$/, "")).join(", ")}` : ""}, expects</span></h4>
        <pre data-testid="script-stdin">{JSON.stringify({ state: entry.input }, null, 2)}</pre>
        {step?.script && <p className="muted small">script <code>{step.script}</code></p>}
      </div>
      <div>
        <h4>stdout</h4>
        <pre data-testid="script-stdout">{JSON.stringify(entry.result, null, 2)}</pre>
      </div>
    </div>
  );
}

function ErrorResult({ result }: { result: Record<string, unknown> }) {
  return (
    <>
      <p className="error" data-testid="step-error">{String(result.error)}</p>
      {typeof result.stderr === "string" && result.stderr && <pre data-testid="step-stderr">{result.stderr}</pre>}
    </>
  );
}

function ClientTask({ result, info }: { result: ClientTaskResult; info: ProcedureInfo }) {
  return (
    <>
      <h4>task</h4>
      <pre className="task" data-testid="task">{result.task}</pre>
      {result.references.length > 0 && (
        <>
          <h4>references the client may load</h4>
          <ul data-testid="references">
            {result.references.map((r) => {
              const path = r.uri.replace(new RegExp(`^${info.name}/`), "");
              return <li key={r.uri}><a href={href({ page: "source", ref: `${info.name}@${info.revision}`, path })}><code>{path}</code></a> — {r.description}</li>;
            })}
          </ul>
        </>
      )}
    </>
  );
}
