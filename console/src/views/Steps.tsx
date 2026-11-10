import { useEffect, useMemo, useState } from "react";
import { api, describe } from "../api/client";
import { folderGraph, isFolderMode } from "../api/console";
import type { RunRecord } from "../api/types";
import { sliceOf, type Graph } from "../graph/bundle.ts";
import { dataEdges, dataKeys, type DataKey } from "../graph/dataflow.ts";
import { layoutOf, type Direction } from "../graph/layout.ts";
import { stepGraphOf, type StepGraph as Model } from "../graph/model.ts";
import { pathOf } from "../graph/traffic.ts";
import { Code } from "../highlight/Code.tsx";
import { DirectionToggle, SPAN, StepGraph, useDirection } from "./StepGraph";
import { TrafficSummary, TrafficTable, useTraffic } from "./Traffic";

/** What the Steps section draws: the step graph in one of its three modes. */
export type StepsView = "control" | "data" | "traffic";

const VIEWS: { view: StepsView; label: string; title: string }[] = [
  { view: "control", label: "control flow", title: "Which step follows which: a route's branches, a loop's passes." },
  { view: "data", label: "data flow", title: "Which step produces each key and which steps read it." },
  { view: "traffic", label: "run traffic", title: "How the recorded runs of this revision went through it." },
];

export const isStepsView = (v: string | null | undefined): v is StepsView => VIEWS.some((x) => x.view === v);

interface StepsProps {
  graph: Graph;
  /** The text of procedure.aip, for the lines that wrote a step. */
  source: string;
  /** The procedure's name and the bundle drawn: run traffic counts the runs of this bundle. */
  name: string;
  bundleId: string | null;
  view: StepsView;
  onView: (view: StepsView) => void;
}

/** A procedure's steps: the step graph as control flow, data flow or run traffic; drawn
 *  down or to the right. Drawn to the right it is wide, and so is a procedure with loops drawn down (a
 *  body hangs beside its loop): the section then takes the whole row of its grid. */
export function Steps({ graph, source, name, bundleId, view: asked, onView }: StepsProps) {
  const [direction, setDirection] = useDirection();
  const [selected, setSelected] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  // The view is the caller's (the address carries it), which may answer a moment later: the radios do not wait.
  const [shown, setShown] = useState(asked);
  useEffect(() => { setShown(asked); }, [asked]);
  const view = shown;
  const choose = (v: StepsView) => { setShown(v); onView(v); };
  const model = useMemo(() => stepGraphOf(graph), [graph]);
  const keys = useMemo(() => dataKeys(graph), [graph]);
  const flow = useMemo(() => dataEdges(keys), [keys]);
  const traffic = useTraffic(model, name, bundleId, view === "traffic");
  useEffect(() => { setSelected(null); setFocusKey(null); }, [graph]);
  const broad = useMemo(() => layoutOf(model, direction).width > SPAN.medium, [model, direction]);
  const wide = direction === "right" || broad;

  return (
    <section className={`steps${wide ? " wide" : ""}`} data-testid="steps" data-view={view} data-direction={direction}>
      <h2>Steps</h2>
      <div className="graph-controls">
        <div className="flow-toggle" role="radiogroup" aria-label="graph">
          {VIEWS.map((v) => (
            <label key={v.view} title={v.title}>
              <input type="radio" name="steps-view" checked={view === v.view} onChange={() => choose(v.view)} /> {v.label}
            </label>
          ))}
        </div>
        <DirectionToggle direction={direction} onChange={setDirection} />
      </div>
      {traffic && <TrafficSummary state={traffic} />}
        <>
          <div className="graph-scroll">
            <StepGraph graph={model} direction={direction} flow={view === "data" ? flow : undefined}
                       traffic={traffic?.state === "ready" ? traffic.traffic : undefined}
                       selected={selected} focusKey={view === "data" ? focusKey : null}
                       onSelect={(id) => { setFocusKey(null); setSelected((s) => (s === id ? null : id)); }} />
          </div>
          {selected && <StepDetail graph={model} id={selected} source={source} onClose={() => setSelected(null)} />}
        </>
      {view === "data" && (
        <>
          <p className="muted small" data-testid="data-hint">Pick a key below, or a step on the graph, to draw its arrows: who produces it and who reads it.</p>
          <DataFlowTable keys={keys} graph={model} focus={focusKey} onFocus={(key) => { setSelected(null); setFocusKey((k) => (k === key ? null : key)); }} />
        </>
      )}
      {traffic?.state === "ready" && traffic.traffic.runs > 0 && <TrafficTable traffic={traffic.traffic} graph={model} />}
    </section>
  );
}

/** The step or loop picked on the graph: what it is, what it reads and produces, and the lines that wrote it. */
function StepDetail({ graph, id, source, onClose }: { graph: Model; id: string; source: string; onClose: () => void }) {
  const node = graph.nodes[id];
  if (!node) return null;
  const card = graph.model.cards[id];
  const slice = sliceOf(source, node.line, node.endLine);
  return (
    <aside className="step-detail" data-testid="step-detail" data-name={node.name}>
      <h3>
        <span className={`kind-tag${node.loop ? " loop" : ""}`} style={node.loop ? undefined : { ["--kind" as string]: `var(--${node.kind})` }}>{node.kind}</span>{" "}
        <code>{node.name}</code>
        <button type="button" onClick={onClose} aria-label="close">×</button>
      </h3>
      <p>{node.loop ? <code>{node.title}</code> : node.title}</p>
      {card && card.sections.length > 0 && (
        <dl>
          {card.sections.map((s) => (
            <div key={s.label} className="detail-row"><dt>{s.label}</dt><dd>{s.rows.map((row, i) => <span key={i}>{i ? ", " : ""}<code>{row}</code></span>)}</dd></div>
          ))}
        </dl>
      )}
      {slice && <div data-testid="step-source" data-first-line={slice.first}><Code text={slice.text} aip firstLine={slice.first} /></div>}
    </aside>
  );
}

/** Every key, who produces it, and who reads it: the graph's data-flow arrows as rows. A key may have several
 *  producers, on different paths. A route's read says whose answer steers it. */
function DataFlowTable({ keys, graph, focus, onFocus }: { keys: DataKey[]; graph: Model; focus: string | null; onFocus: (key: string) => void }) {
  const name = (id: string) => graph.nodes[id]?.name ?? id;
  return (
    <table className="compact" aria-label="data flow">
      <thead><tr><th>key</th><th>type</th><th>produced by</th><th>read by</th></tr></thead>
      <tbody>
        {keys.map((k) => (
          <tr key={k.key} data-testid="data-flow-row" data-key={k.key} data-from={k.producers.map(name).join(",")}
              data-to={[...new Set(k.readers.map((r) => name(r.node)))].join(",")} aria-current={focus === k.key ? "true" : undefined}>
            <td><button type="button" className="linkish" aria-pressed={focus === k.key} onClick={() => onFocus(k.key)}><code>{k.key}</code></button></td>
            <td>{k.type ? <code>{k.type}{k.labels.length ? ` [${k.labels.join(", ")}]` : ""}</code> : <span className="muted">—</span>}</td>
            <td>
              {k.producers.length === 0 && <span className="muted">no step</span>}
              {k.producers.map((p, i) => <span key={p}>{i ? ", " : ""}<code>{name(p)}</code></span>)}
              {k.producers.length > 1 && <span className="muted small"> (on different paths)</span>}
            </td>
            <td>
              {k.readers.length === 0 && <span className="muted">no step</span>}
              {k.readers.map((r, i) => (
                <span key={i} data-testid="key-read" data-node={name(r.node)} data-how={r.how} data-source={r.source ?? undefined}>
                  {i ? ", " : ""}<code>{name(r.node)}</code>
                  {(r.field || r.how !== "read") && <span className="muted small"> ({[r.field && `.${r.field}`, r.how !== "read" && r.how].filter(Boolean).join(", ")})</span>}
                  {r.source && <> <span className={`status-tag source-${r.source}`} data-testid="source-class" title={`This route is steered by ${SOURCES[r.source] ?? r.source}.`}>{r.source}</span></>}
                </span>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A route's source class (spec 2.2), in words. */
const SOURCES: Record<string, string> = {
  measured: "a decision model's answer, which carries a confidence",
  scripted: "a script's answer",
  agent: "an agent's answer, which carries no confidence",
  input: "an input of the run",
  aggregated: "an aggregation, which has no confidence of its own",
};

// ------------------------------------------------------------------ one run's path

/** The graph of the bundle a run ran: the server's, or in folder mode the folder as it compiles now. */
function useRunGraph(bundleId: string): { graph: Graph | null; stale: boolean; error: string | null } {
  const [got, setGot] = useState<{ graph: Graph; stale: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setGot(null);
    setError(null);
    const asked = isFolderMode()
      ? folderGraph().then((f) => (f.graph ? { graph: f.graph, stale: f.bundle_id !== bundleId } : Promise.reject(new Error("the folder does not compile now, so there is no graph to draw the run over"))))
      : api.bundleGraph(bundleId).then((b) => ({ graph: b.graph, stale: false }));
    asked.then(setGot).catch((e: unknown) => setError(describe(e)));
  }, [bundleId]);
  return { graph: got?.graph ?? null, stale: got?.stale ?? false, error };
}

/** A run drawn over the step graph: the steps it reached and the arrows it took heavy, an arrow a loop
 *  repeated badged with how many times, and where it waits or failed marked. */
export function RunPath({ record, direction }: { record: RunRecord; direction: Direction }) {
  const { graph, stale, error } = useRunGraph(record.bundle_id);
  const model = useMemo(() => (graph ? stepGraphOf(graph) : null), [graph]);
  const path = useMemo(() => (model ? pathOf(model, record) : null), [model, record]);
  if (error) return <p className="muted small" data-testid="run-path-error">{error}</p>;
  if (!model || !path) return <p className="muted small">Loading the graph…</p>;
  return (
    <>
      {stale && <p className="muted small" data-testid="run-path-stale">The folder has changed since this run: this is its graph as it compiles now.</p>}
      <div className="graph-scroll" data-testid="run-path" data-waiting={path.waiting ? model.nodes[path.waiting].name : undefined}
           data-failed={path.failed ? model.nodes[path.failed].name : undefined}>
        <StepGraph graph={model} direction={direction} path={path} />
      </div>
    </>
  );
}
