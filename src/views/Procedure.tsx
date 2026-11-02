import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CatalogEntry, ProcedureInfo, Question, Resource, StepDetail, StepInput, StepOutput } from "../api/types";
import { dataFlow, groupFlow, START_INPUT } from "../graph/dataflow";
import { href, navigate } from "../router";
import { Requires } from "./Requires";
import { describe } from "./Source";
import { DirectionToggle, StepGraph, useDirection } from "./StepGraph";
import { TrafficSummary, TrafficTable, useTraffic } from "./Traffic";
import { DownloadZip, PublishedBanner } from "./Zip";

export function Procedure({ reference }: { reference: string }) {
  const [info, setInfo] = useState<ProcedureInfo | null>(null);
  const [entry, setEntry] = useState<CatalogEntry | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped after pin or retire: both fetches run again, the page stays up meanwhile.
  const [version, setVersion] = useState(0);
  const [mode, setMode] = useState<"control" | "data" | "traffic">("control");
  const [direction, setDirection] = useDirection();
  const name = reference.split("@")[0];
  const flow = useMemo(() => (info ? dataFlow(info) : []), [info]);
  const traffic = useTraffic(name, info?.revision ?? "", mode === "traffic" && info !== null);

  useEffect(() => {
    setError(null);
    api.info(reference).then(setInfo).catch((e: unknown) => {
      setError(e instanceof ApiError ? `${e.kind}: ${e.message}` : String(e));
    });
  }, [reference, version]);
  useEffect(() => { setInfo(null); }, [reference]);

  useEffect(() => {
    api.catalog().then((all) => setEntry(all.find((c) => c.name === name) ?? null)).catch(() => setEntry(null));
  }, [name, version]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (info === null) return <p className="muted">Loading {reference}…</p>;

  const byStep = <T extends { step: string }>(rows: T[], step: string) => rows.filter((r) => r.step === step);
  // Revisions are newest first; the one after the current is the one published before it.
  const revisions = entry?.revisions.map((r) => r.revision) ?? [];
  const previous = revisions[revisions.indexOf(info.revision) + 1];

  return (
    <article className="procedure">
      <nav className="crumbs"><a href={href({ page: "catalog" })}>catalog</a> / <code>{info.name}</code></nav>
      <h1>
        {info.name}
        <span className="muted rev"> @{info.revision}{info.retired ? " (retired)" : ""}</span>
      </h1>
      <p>{info.description}</p>
      <PublishedBanner key={info.id} reference={info.id} />

      <div className="procedure-grid">
        {/* Left to right, the graph is wide: the section takes the whole row and the rest moves below. */}
        <section className={direction === "right" ? "wide" : undefined}>
          <h2>Steps</h2>
          <div className="graph-controls">
            <div className="flow-toggle" role="radiogroup" aria-label="graph">
              <label><input type="radio" name="flow" checked={mode === "control"} onChange={() => setMode("control")} /> control flow</label>
              <label><input type="radio" name="flow" checked={mode === "data"} onChange={() => setMode("data")} /> data flow</label>
              <label><input type="radio" name="flow" checked={mode === "traffic"} onChange={() => setMode("traffic")} /> run traffic</label>
            </div>
            <DirectionToggle direction={direction} onChange={setDirection} />
          </div>
          {traffic && <TrafficSummary state={traffic} />}
          <StepGraph steps={info.step_details} edges={info.edges} branches={info.branches}
                     start={info.start.step} end={info.end.step} flow={mode === "data" ? groupFlow(flow) : undefined}
                     traffic={traffic?.state === "ready" ? traffic.traffic : undefined} direction={direction} />
          {mode === "data" && <DataFlowTable info={info} flow={flow} />}
          {traffic?.state === "ready" && traffic.traffic.runs > 0 && <TrafficTable traffic={traffic.traffic} steps={info.step_details.map((s) => s.name)} />}
        </section>

        <section>
          <h2>Revisions</h2>
          <RevisionPicker entry={entry} current={info.revision} name={info.name} />
          <p className="links">
            <a href={href({ page: "source", ref: `${info.name}@${info.revision}` })}>source</a>
            <span className="muted"> · {info.files.length} files</span>
            {previous && <> · <a href={href({ page: "diff", name: info.name, a: previous, b: info.revision })}>diff with previous</a></>}
            {" · "}<a href={href({ page: "run", ref: `${info.name}@${info.revision}` })}>run</a>
            {" · "}<a href={href({ page: "runs", name: info.name })}>history</a>
            {" · "}<DownloadZip name={info.name} revision={info.revision} />
            {" · "}<a href={href({ page: "studio", import: `${info.name}@${info.revision}` })} data-testid="edit-in-studio">edit in Studio</a>
          </p>

          <h2>Purpose</h2>
          <p className="prose">{info.purpose}</p>
          <List title="Use when" items={info.trigger_when} />
          <List title="Do not use when" items={info.do_not_use_when} />
          <List title="Anti-patterns" items={info.anti_patterns} />

          <h2>Start input</h2>
          <p className="muted">Step <code>{info.start.step}</code> ({info.start.kind})</p>
          <pre data-testid="example-input">{JSON.stringify(info.example_input, null, 2)}</pre>

          <h2>Requires</h2>
          <p className="muted small">What the machine that runs the scripts must have: the client checks it before the first execution step.</p>
          <Requires requires={info.requires} />
        </section>
      </div>

      <Governance key={info.id} info={info} entry={entry} onChanged={() => setVersion((v) => v + 1)} />

      <h2>Step details</h2>
      {info.step_details.map((s) => (
        <StepCard key={s.name} step={s} isStart={s.name === info.start.step} isEnd={s.name === info.end.step}
                  inputs={byStep(info.inputs, s.name)} outputs={byStep(info.outputs ?? [], s.name)} questions={byStep(info.questions, s.name)}
                  resources={byStep(info.resources, s.name)} branches={info.branches.filter((b) => b.router === s.name)}
                  next={info.edges.find((e) => e.from === s.name)?.to} />
      ))}
    </article>
  );
}

function RevisionPicker({ entry, current, name }: { entry: CatalogEntry | null; current: string; name: string }) {
  if (!entry) return <p className="muted">—</p>;
  return (
    <select aria-label="revision" value={current}
            onChange={(e) => navigate({ page: "procedure", ref: `${name}@${e.target.value}` })}>
      {entry.revisions.map((r) => (
        <option key={r.revision} value={r.revision}>
          {r.revision}{r.revision === entry.pinned ? " · pinned" : ""}{r.revision === entry.latest ? " · latest" : ""}
          {r.retired ? " · retired" : ""} — {r.published_at.slice(0, 10)}
        </option>
      ))}
    </select>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <>
      <h3>{title}</h3>
      <ul>{items.map((it, i) => <li key={i}>{it}</li>)}</ul>
    </>
  );
}

interface CardProps {
  step: StepDetail; isStart: boolean; isEnd: boolean;
  inputs: StepInput[]; outputs: StepOutput[]; questions: Question[]; resources: Resource[];
  branches: { value: string; to: string }[]; next?: string;
}

function StepCard({ step, isStart, isEnd, inputs, outputs, questions, resources, branches, next }: CardProps) {
  return (
    <section className={`step-card kind-${step.kind}`} id={`step-${step.name}`}>
      <h3>
        <code>{step.name}</code> <span className="kind-tag">{step.kind}</span>
        {isStart && <span className="muted"> · start</span>}{isEnd && <span className="muted"> · end</span>}
      </h3>
      {step.description && <p>{step.description}</p>}
      <dl>
        {step.kind === "router" && <><dt>branch on</dt><dd><code>{step.branch_on}</code></dd></>}
        {step.kind === "execution" && <><dt>script</dt><dd><code>{step.script}</code>{step.timeout ? ` (timeout ${step.timeout}s)` : ""}</dd></>}
        {step.kind === "execution" && <><dt>command</dt><dd data-testid="command"><code>{step.command ? step.command.join(" ") : `python ${step.script?.replace(/^.*\//, "")}`}</code>{!step.command && <span className="muted"> (default)</span>}</dd></>}
        {step.kind === "client_task" && <><dt>template</dt><dd><code>{step.template}</code>{step.framing ? " · framed" : ""}</dd></>}
        {next && <><dt>inputs to</dt><dd><a href={`#step-${next}`}><code>{next}</code></a></dd></>}
      </dl>
      {branches.length > 0 && (
        <table className="compact"><thead><tr><th>value</th><th>to</th></tr></thead>
          <tbody>{branches.map((b) => <tr key={b.value}><td><code>{b.value}</code></td><td><a href={`#step-${b.to}`}><code>{b.to}</code></a></td></tr>)}</tbody>
        </table>
      )}
      {inputs.length > 0 && (
        <table className="compact"><thead><tr><th>input</th><th>type</th><th>description</th></tr></thead>
          <tbody>{inputs.map((i) => <tr key={i.name}><td><code>{i.name}</code></td><td>{i.type}</td><td>{i.description ?? ""}</td></tr>)}</tbody>
        </table>
      )}
      {outputs.length > 0 && (
        <table className="compact" data-testid="outputs"><thead><tr><th>output</th><th>type</th><th>description</th></tr></thead>
          <tbody>{outputs.map((o) => <tr key={o.name}><td><code>{o.name}</code></td><td>{o.type}</td><td>{o.description ?? ""}</td></tr>)}</tbody>
        </table>
      )}
      {questions.length > 0 && (
        <table className="compact"><thead><tr><th>question</th><th>type</th><th>threshold</th><th>instructions</th></tr></thead>
          <tbody>{questions.map((q) => (
            <tr key={q.name}>
              <td><code>{q.name}</code></td><td>{q.type}</td>
              <td>{q.threshold ?? <span className="muted">default</span>}</td>
              <td>{q.instructions}{q.criteria && <Criteria text={q.criteria} />}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {resources.length > 0 && (
        <table className="compact"><thead><tr><th>resource</th><th>role</th><th>description</th></tr></thead>
          <tbody>{resources.map((r) => <tr key={r.path}><td><code>{r.path}</code></td><td>{r.role}</td><td>{r.description ?? ""}</td></tr>)}</tbody>
        </table>
      )}
    </section>
  );
}

/** Every key, who produces it, and who reads it: the graph's data-flow arrows as rows. */
function DataFlowTable({ info, flow }: { info: ProcedureInfo; flow: { key: string; from: string; to: string }[] }) {
  const keys: { key: string; from: string; to: string[] }[] = [];
  for (const e of flow) {
    const row = keys.find((k) => k.key === e.key);
    if (row) row.to.push(e.to);
    else keys.push({ key: e.key, from: e.from, to: [e.to] });
  }
  // A key no step reads (a step's output kept only in the history) still has its producer.
  const produced = [...(info.outputs ?? []).map((o) => [o.name, o.step]), ...info.questions.map((q) => [q.name, q.step])];
  for (const [key, from] of produced) if (!keys.some((k) => k.key === key)) keys.push({ key, from, to: [] });
  const step = (s: string) => (s === START_INPUT ? <span className="muted">start input</span> : <a href={`#step-${s}`}><code>{s}</code></a>);
  return (
    <table className="compact" aria-label="data flow">
      <thead><tr><th>key</th><th>produced by</th><th>read by</th></tr></thead>
      <tbody>
        {keys.map((k) => (
          <tr key={k.key} data-testid="data-flow-row" data-key={k.key} data-from={k.from} data-to={k.to.join(",")}>
            <td><code>{k.key}</code></td>
            <td>{step(k.from)}</td>
            <td>{k.to.length ? k.to.map((t, i) => <span key={t}>{i ? ", " : ""}{step(t)}</span>) : <span className="muted">no step (kept in the history)</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Criteria({ text }: { text: string }) {
  let parsed: Record<string, string> | null = null;
  try { parsed = JSON.parse(text); } catch { /* shown raw */ }
  if (!parsed) return <pre>{text}</pre>;
  return <ul className="criteria">{Object.entries(parsed).map(([k, v]) => <li key={k}><code>{k}</code>: {v}</li>)}</ul>;
}

// ------------------------------------------------------------------ governance (view 5a, §7)

interface GovernanceProps { info: ProcedureInfo; entry: CatalogEntry | null; onChanged: () => void }

/** Pin and retire this revision. Both need the publish scope: a 403 points at the Server page, where the token
 *  is set. Thresholds are the author's, from SKILL.md, so there is nothing to override here. */
function Governance({ info, entry, onChanged }: GovernanceProps) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRetire, setConfirmRetire] = useState(false);

  const pinned = entry?.pinned ?? null;
  const isPinned = pinned === info.revision;

  const act = async (what: string, call: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await call();
      setNote(done);
      onChanged();
    } catch (e) {
      const forbidden = e instanceof ApiError && (e.status === 401 || e.status === 403);
      setError(`${what} failed: ${describe(e)}${forbidden ? ". Set a token with the publish scope on the Server page." : ""}`);
    } finally {
      setBusy(false);
    }
  };

  const short = (r: string) => r.slice(0, 8);

  return (
    <section className="governance-box" data-testid="governance">
      <h2>Governance</h2>
      <div className="governance-grid">
        <div>
          <h3>Pin</h3>
          <p className="muted small">The bare name resolves to the pinned revision; with no pin, to the latest live one.</p>
          <p data-testid="pin-state">
            {pinned ? <>pinned <code>{short(pinned)}</code>{isPinned ? " (this revision)" : ""}</> : "no pin"}
          </p>
          <div className="actions">
            {!isPinned && !info.retired && (
              <button type="button" disabled={busy}
                      onClick={() => void act("pin", () => api.pin(info.name, info.revision), `Pinned ${short(info.revision)}.`)}>
                Pin this revision
              </button>
            )}
            {pinned && (
              <button type="button" disabled={busy} onClick={() => void act("unpin", () => api.pin(info.name, null), "Unpinned.")}>
                Unpin
              </button>
            )}
          </div>

          <h3>Retire</h3>
          <p className="muted small">A retired revision stays readable and runnable by exact reference, but the name no longer resolves to it.</p>
          {info.retired ? <p data-testid="retired-state">This revision is retired.</p> : (
            <div className="actions">
              {!confirmRetire && <button type="button" disabled={busy} onClick={() => setConfirmRetire(true)}>Retire this revision…</button>}
              {confirmRetire && (
                <>
                  <span>Retire <code>{short(info.revision)}</code>? This cannot be undone.</span>
                  <button type="button" disabled={busy}
                          onClick={() => { setConfirmRetire(false); void act("retire", () => api.retire(info.name, info.revision), `Retired ${short(info.revision)}.`); }}>
                    Confirm retire
                  </button>
                  <button type="button" onClick={() => setConfirmRetire(false)}>Cancel</button>
                </>
              )}
            </div>
          )}
        </div>

      </div>
      {note && <p className="muted" data-testid="governance-note">{note}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
