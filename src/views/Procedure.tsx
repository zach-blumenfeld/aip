import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CatalogEntry, ProcedureInfo, PublishIssue, Question, Resource, StepDetail, StepInput, StepOutput } from "../api/types";
import { dataFlow, groupFlow, outputsOf } from "../graph/dataflow";
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
          <p className="muted">
            The <code>{info.start.step}</code> step holds what the client supplies and hands the run to{" "}
            <a href={`#step-${info.edges.find((e) => e.from === info.start.step)?.to ?? ""}`}><code>{info.edges.find((e) => e.from === info.start.step)?.to}</code></a>. An example:
          </p>
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
                  issues={(info.issues ?? []).filter((i) => i.step === s.name)}
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
  /** The validator's warnings and infos on this step at publish. */
  issues: PublishIssue[];
}

/** What a router's source class means, for the tag's title. */
const CLASS_TITLES = {
  deterministic: "deterministic: the branch key is a start input or a script's output",
  measured: "measured: a decision model answers the branch key and this router checks its confidence",
  unmeasured: "unmeasured: a probabilistic choice routes the run (a decision the client may answer by hand, or a client task) and nothing calibrated records how sure it was",
};

function SourceClassTag({ cls }: { cls: StepDetail["source_class"] }) {
  if (!cls) return <span className="muted">unclassified</span>;
  return <span className={`status-tag class-${cls}`} data-testid="source-class" data-class={cls} title={CLASS_TITLES[cls]}>{cls}</span>;
}

function StepCard({ step, isStart, isEnd, inputs, outputs, questions, resources, branches, next, issues }: CardProps) {
  return (
    <section className={`step-card kind-${step.kind}`} id={`step-${step.name}`}>
      <h3>
        <code>{step.name}</code> <span className="kind-tag">{step.kind}</span>
        {isStart && <span className="muted"> · start</span>}{isEnd && <span className="muted"> · end</span>}
      </h3>
      {step.description && <p>{step.description}</p>}
      {isStart && <p className="muted small">The procedure's inputs: what the client supplies when it opens a run.</p>}
      <dl>
        {step.kind === "router" && <><dt>branch on</dt><dd><code>{step.branch_on}</code> · source <SourceClassTag cls={step.source_class} /></dd></>}
        {step.kind === "router" && (
          <><dt>confidence check</dt>
            <dd data-testid="router-check">
              {step.check
                ? <>when <code>{step.check.key}</code> is below <code>{step.check.below}</code>, or absent, go to <a href={`#step-${step.check.to}`}><code>{step.check.to}</code></a></>
                : <span className="muted">none</span>}
            </dd></>
        )}
        {step.kind === "decision" && (
          <><dt>fallback</dt>
            <dd data-testid="fallback" data-fallback={step.fallback ? "true" : "false"}>
              {step.fallback
                ? <>on <span className="muted">· a client with no decision model may answer by hand, which records no confidence</span></>
                : <>off <span className="muted">· a client with no decision model stops here (<code>no_decision_model</code>)</span></>}
            </dd></>
        )}
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
        <table className="compact" data-testid="questions"><thead><tr><th>question</th><th>type</th><th>confidence</th><th>instructions</th></tr></thead>
          <tbody>{questions.map((q) => (
            <tr key={q.name} data-question={q.name} data-confidence={q.confidence ? "true" : "false"}>
              <td><code>{q.name}</code></td><td>{q.type}</td>
              <td>{q.confidence ? <>emits <code>{q.name}_confidence</code></> : <span className="muted">not emitted</span>}</td>
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
      {issues.length > 0 && (
        <ul className="publish-issues small" data-testid="publish-issues">
          {issues.map((i, n) => (
            <li key={n} data-code={i.code} data-severity={i.severity}>
              <span className={`status-tag ${i.severity === "warning" ? "flagged" : ""}`}>{i.severity}</span> {i.message} <code className="muted">{i.code}</code>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Every key, who produces it, and who reads it: the graph's data-flow arrows as rows. A key may have several
 *  producers (a later one overwrites the value where a run passes through both); the start step produces the
 *  procedure's inputs. */
function DataFlowTable({ info, flow }: { info: ProcedureInfo; flow: { key: string; from: string; to: string }[] }) {
  const keys: { key: string; from: string[]; to: string[] }[] = [];
  const row = (key: string) => {
    let r = keys.find((k) => k.key === key);
    if (!r) { r = { key, from: [], to: [] }; keys.push(r); }
    return r;
  };
  const ordered = [...info.step_details].sort((a, b) => a.order - b.order);
  for (const s of ordered) for (const key of outputsOf(info, s.name)) { const r = row(key); if (!r.from.includes(s.name)) r.from.push(s.name); }
  for (const e of flow) { const r = row(e.key); if (!r.to.includes(e.to)) r.to.push(e.to); }
  const step = (s: string) => <a href={`#step-${s}`}><code>{s}</code></a>;
  const list = (names: string[]) => names.map((t, i) => <span key={t}>{i ? ", " : ""}{step(t)}</span>);
  return (
    <table className="compact" aria-label="data flow">
      <thead><tr><th>key</th><th>produced by</th><th>read by</th></tr></thead>
      <tbody>
        {keys.map((k) => (
          <tr key={k.key} data-testid="data-flow-row" data-key={k.key} data-from={k.from.join(",")} data-to={k.to.join(",")}>
            <td><code>{k.key}</code></td>
            <td>{list(k.from)}{k.from.length > 1 && <span className="muted small"> (the later overwrites)</span>}</td>
            <td>{k.to.length ? list(k.to) : <span className="muted">no step (kept in the history)</span>}</td>
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
 *  is set. A router's confidence check and a decision's `fallback` are the author's, in SKILL.md, so there is
 *  nothing to override here. */
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
