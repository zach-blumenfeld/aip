import { useMemo, useState, type KeyboardEvent } from "react";
import type { DataEdge } from "../graph/dataflow.ts";
import { layoutOf, SIZE, type Box, type Direction, type GraphLayout } from "../graph/layout.ts";
import { edgeKey, edgeLabel, type StepGraph as Model } from "../graph/model.ts";
import type { RunPath, Traffic } from "../graph/traffic.ts";

const PAD = 24;
// A data-flow arrow bows a little to one side of the straight line between its nodes, so it does not lie
// on the control arrow between them and the arrow back bows the other way.
const BOW = 22;
/** How wide a drawing a column beside other things holds: past `narrow` a run's path takes the row of
 *  its page, past `medium` the procedure page's steps do. */
export const SPAN = { narrow: 400, medium: 640 };
export const spanOf = (width: number) => (width > SPAN.medium ? "wide" : width > SPAN.narrow ? "medium" : "narrow");

interface Props {
  graph: Model;
  /** Layers top-down, or left-to-right. */
  direction?: Direction;
  /** Data flow: the control edges go faint, and the arrows of the key or the node picked are drawn over them, one
   *  dashed arrow per (producer, reader) with the keys it carries. With nothing picked no data arrow is drawn. */
  flow?: DataEdge[];
  /** Weight the control edges by the runs that took them and badge each step with the runs that reached it. */
  traffic?: Traffic;
  /** One run: the steps it reached and the arrows it took drawn heavy, where it waits or failed marked. */
  path?: RunPath;
  /** A node, step or loop, is a button that selects it. */
  onSelect?: (id: string) => void;
  selected?: string | null;
  /** In data flow, the key whose arrows are drawn; without one, the selected node's are. */
  focusKey?: string | null;
}

/** The step graph: steps as nodes with their kind, a loop as a node with its body hung beside it, the
 *  control edges as arrows with a route's branches labelled. */
export function StepGraph({ graph, direction = "down", flow, traffic, path, onSelect, selected, focusKey }: Props) {
  const g = useMemo(() => layoutOf(graph, direction), [graph, direction]);
  const data = useMemo(() => {
    if (!flow) return [];
    // Only what was picked: every arrow of a procedure at once is a tangle, and the table under the graph is the overview.
    const picked = focusKey ? flow.filter((f) => f.keys.includes(focusKey)).map((f) => ({ ...f, keys: [focusKey] }))
      : selected ? flow.filter((f) => f.from === selected || f.to === selected) : [];
    return routeData(picked, g);
  }, [flow, g, focusKey, selected]);
  const width = g.width + 2 * PAD;
  const height = g.height + 2 * PAD;
  const busiest = traffic ? Math.max(1, ...traffic.edges.values()) : 1;
  const loops = Object.values(graph.nodes).filter((n) => n.loop);
  const steps = Object.values(graph.nodes).filter((n) => !n.loop);
  const mode = flow ? "data" : traffic ? "traffic" : path ? "path" : "control";
  const pick = (id: string) => onSelect && {
    role: "button", tabIndex: 0, "aria-pressed": selected === id,
    onClick: () => onSelect(id),
    onKeyDown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(id); } },
  };

  return (
    <svg className={`step-graph ${mode}-mode`} role="img" aria-label="step graph" data-testid="step-graph" data-direction={direction} data-mode={mode} data-span={spanOf(width)}
         viewBox={`${-PAD} ${-PAD} ${width} ${height}`} width={width} height={height}>
      <defs>
        {/* userSpaceOnUse: the head stays this size however thick the line is drawn. */}
        <marker id="sg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="arrow-head" />
        </marker>
        <marker id="sg-arrow-loop" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="loop-arrow" />
        </marker>
        <marker id="sg-arrow-busy" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="10" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="busy-arrow" />
        </marker>
        <marker id="sg-arrow-data" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="data-arrow" />
        </marker>
      </defs>

      {g.edges.map((e) => {
        const d = e.points.map(([x, y], i) => `${i ? "L" : "M"} ${x} ${y}`).join(" ");
        const from = graph.nodes[e.edge.from].name, to = graph.nodes[e.edge.to].name;
        const times = path ? path.taken.get(e.edge.key) ?? 0 : null;
        const runs = traffic ? traffic.edges.get(e.edge.key) ?? 0 : null;
        // Traffic: width grows with the square root of the share, so a rare branch still reads as a line.
        const stroke = runs !== null ? (runs ? 1.5 + 6 * Math.sqrt(runs / busiest) : 1) : times ? 2.75 : 1.25;
        const label = edgeLabel(e.edge);
        const count = runs ? String(runs) : times !== null && times > 1 ? `×${times}` : "";
        const kinds = e.edge.ways.map((w) => w.kind).join(" ");
        return (
          <g key={e.edge.key} className={`edge${times ? " taken" : ""}${runs ? " busy" : runs === 0 ? " idle" : ""}${e.rail ? " rail" : ""}${e.edge.enter ? " enter" : ""}`}
             data-testid="step-edge" data-from={from} data-to={to} data-kinds={kinds} data-label={label || undefined}
             data-taken={times !== null ? String(times > 0) : undefined} data-times={times ?? undefined} data-runs={runs ?? undefined}>
            <path d={d} fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinejoin="round"
                  strokeDasharray={kinds === "below" ? "6 3" : undefined} markerEnd={runs ? "url(#sg-arrow-busy)" : mode === "control" && (e.rail || e.edge.enter) ? "url(#sg-arrow-loop)" : "url(#sg-arrow)"} />
            {(label || count) && (
              <text x={e.label[0]} y={e.label[1] + 4} textAnchor={e.anchor} className="branch-label">
                {label && <tspan data-testid="branch-label">{label}</tspan>}
                {count && <tspan className="run-count" data-testid={runs ? "edge-runs" : "edge-times"}>{label ? " " : ""}{count}</tspan>}
              </text>
            )}
          </g>
        );
      })}

      {data.map((d) => (
        <g key={`${d.from}=>${d.to}`} className="data-edge" data-testid="data-edge"
           data-from={graph.nodes[d.from].name} data-to={graph.nodes[d.to].name} data-keys={d.keys.join(",")}>
          <path d={d.path} fill="none" stroke="currentColor" strokeWidth={2} strokeDasharray="5 3" markerEnd="url(#sg-arrow-data)" />
          {/* With one key picked every arrow carries it, and the table says which: only a picked step's arrows are named. */}
          {!focusKey && <text x={d.label[0]} y={d.label[1]} textAnchor={d.anchor} className="data-label" data-testid="data-label">{d.keys.join(", ")}</text>}
        </g>
      ))}

      {steps.map((step) => {
        const box = g.boxes[step.id];
        if (!box) return null;
        const reached = path?.visited.has(step.id);
        const state = path?.waiting === step.id ? "waiting" : path?.failed === step.id ? "failed" : null;
        const W = SIZE.nodeWidth, H = SIZE.nodeHeight;
        return (
          <g key={step.id} className={`node kind-${step.kind}${reached ? " visited" : ""}${selected === step.id ? " selected" : ""}${state ? ` ${state}` : ""}`}
             transform={`translate(${box.x}, ${box.y})`} data-testid="step-node" data-step={step.name} data-kind={step.kind}
             data-visited={path ? String(!!reached) : undefined} data-state={state ?? undefined}
             data-runs={traffic ? traffic.nodes.get(step.id) ?? 0 : undefined} aria-label={`${step.name} (${step.kind})`} {...pick(step.id)}>
            <title>{step.title}</title>
            <rect width={W} height={H} rx={step.kind === "Route" || step.kind === "Start" ? H / 2 : 6} />
            {step.kind === "End" && <rect x={3} y={3} width={W - 6} height={H - 6} rx={4} className="end-ring" />}
            {step.kind === "Start" && <circle cx={0} cy={H / 2} r={5} className="start-dot" />}
            <text x={W / 2} y={H / 2 - 4} textAnchor="middle" className="node-name">{clip(step.name, W - 12, 7.6)}</text>
            <text x={W / 2} y={H / 2 + 13} textAnchor="middle" className="node-kind">{step.kind}</text>
            {traffic && <Badge x={W} y={0} runs={traffic.nodes.get(step.id) ?? 0} failed={traffic.failed.get(step.id) ?? 0} total={traffic.runs} />}
            {state && <Mark x={W} y={0} kind={state} />}
          </g>
        );
      })}

      {loops.map((loop) => {
        const box = g.boxes[loop.id];
        if (!box) return null;
        const reached = path?.visited.has(loop.id);
        const failed = path?.failed === loop.id;
        // A pass enters the body once: the arrow in counts them.
        const passes = path && loop.children.length ? path.taken.get(edgeKey(loop.id, loop.children[0])) ?? 0 : null;
        return (
          <g key={loop.id} className={`node loop-node${reached ? " visited" : ""}${selected === loop.id ? " selected" : ""}${failed ? " failed" : ""}`}
             transform={`translate(${box.x}, ${box.y})`} data-testid="loop-node" data-loop={loop.name} data-kind={loop.kind}
             data-visited={path ? String(!!reached) : undefined} data-state={failed ? "failed" : undefined} data-passes={passes ?? undefined}
             data-runs={traffic ? traffic.nodes.get(loop.id) ?? 0 : undefined} aria-label={`${loop.name} (${loop.kind})`} {...pick(loop.id)}>
            <title>{`${loop.kind} ${loop.name} ${loop.title}`}</title>
            <rect width={box.w} height={box.h} rx={6} />
            <text x={box.w / 2} y={20} textAnchor="middle" className="node-name">{clip(loop.name, box.w - 12, 7.6)}</text>
            <text x={box.w / 2} y={36} textAnchor="middle" className="node-kind">↻ {loop.kind}</text>
            <text x={box.w / 2} y={53} textAnchor="middle" className="loop-summary" data-testid="loop-summary">{clip(loop.summary, box.w - 16, 6.5)}</text>
            {traffic && <Badge x={box.w} y={0} runs={traffic.nodes.get(loop.id) ?? 0} failed={traffic.failed.get(loop.id) ?? 0} total={traffic.runs} />}
            {passes !== null && passes > 0 && <Passes x={box.w} y={failed ? box.h : 0} passes={passes} />}
            {failed && <Mark x={box.w} y={0} kind="failed" />}
          </g>
        );
      })}
    </svg>
  );
}

/** `text` cut to what `width` pixels hold. */
function clip(text: string, width: number, perChar = 6.6): string {
  const most = Math.floor(width / perChar);
  if (most < 4) return "";
  return text.length <= most ? text : `${text.slice(0, most - 1)}…`;
}

/** The runs that reached a step, pinned to its top-right corner; red when some failed there. */
function Badge({ x, y, runs, failed, total }: { x: number; y: number; runs: number; failed: number; total: number }) {
  const text = failed ? `${runs} · ${failed} failed` : String(runs);
  const w = 8 + 6.5 * text.length;
  return (
    <g className={`badge${failed ? " failed" : runs ? "" : " none"}`} transform={`translate(${x - w + 8}, ${y - 9})`} data-testid="step-runs"
       data-runs={runs} data-failed={failed}>
      <title>{runs} of {total} runs reached this{failed ? `, ${failed} failed here` : ""}</title>
      <rect width={w} height={18} rx={9} />
      <text x={w / 2} y={13} textAnchor="middle">{text}</text>
    </g>
  );
}

/** How many passes of a loop a run made, pinned to the loop node's corner. */
function Passes({ x, y, passes }: { x: number; y: number; passes: number }) {
  const text = passes === 1 ? "1 pass" : `${passes} passes`;
  const w = 8 + 6.3 * text.length;
  return (
    <g className="badge passes" transform={`translate(${x - w + 8}, ${y - 9})`} data-testid="loop-passes" data-passes={passes}>
      <title>The run made {text} of this loop</title>
      <rect width={w} height={18} rx={9} />
      <text x={w / 2} y={13} textAnchor="middle">{text}</text>
    </g>
  );
}

/** Where a run waits, or where it failed. */
function Mark({ x, y, kind }: { x: number; y: number; kind: "waiting" | "failed" }) {
  const text = kind === "waiting" ? "waiting here" : "failed here";
  const w = 8 + 6.3 * text.length;
  return (
    <g className={`badge mark-${kind}`} transform={`translate(${x - w + 8}, ${y - 9})`} data-testid="path-mark" data-mark={kind}>
      <rect width={w} height={18} rx={9} />
      <text x={w / 2} y={13} textAnchor="middle">{text}</text>
    </g>
  );
}

interface Routed extends DataEdge { path: string; label: [number, number]; anchor: "start" | "middle" | "end" }

/** Paths for the data arrows: from the edge of the producer to the edge of the reader along the line
 *  between their middles, bowed to its left, with the keys named at the top of the bow. */
function routeData(flow: DataEdge[], g: GraphLayout): Routed[] {
  /** Where the line from the middle of `box` towards (x, y) leaves it. */
  const leave = (box: Box, x: number, y: number): [number, number] => {
    const cx = box.x + box.w / 2, cy = box.y + box.h / 2, dx = x - cx, dy = y - cy;
    const t = Math.min(dx ? box.w / 2 / Math.abs(dx) : Infinity, dy ? box.h / 2 / Math.abs(dy) : Infinity);
    return [cx + dx * t, cy + dy * t];
  };
  const out: Routed[] = [];
  for (const f of flow) {
    const a = g.boxes[f.from], b = g.boxes[f.to];
    if (!a || !b) continue;
    const ca = [a.x + a.w / 2, a.y + a.h / 2], cb = [b.x + b.w / 2, b.y + b.h / 2];
    const length = Math.hypot(cb[0] - ca[0], cb[1] - ca[1]) || 1;
    // The bow's control point: off the middle of the line, to the left of the way it goes.
    const nx = (cb[1] - ca[1]) / length, ny = -(cb[0] - ca[0]) / length;
    const mx = (ca[0] + cb[0]) / 2 + nx * 2 * BOW, my = (ca[1] + cb[1]) / 2 + ny * 2 * BOW;
    const [x0, y0] = leave(a, mx, my), [x1, y1] = leave(b, mx, my);
    // A quadratic's top is halfway from the middle of its ends to its control point.
    const top: [number, number] = [(x0 + x1) / 4 + mx / 2, (y0 + y1) / 4 + my / 2];
    const sideways = Math.abs(nx) > Math.abs(ny);
    out.push({ ...f, path: `M ${x0} ${y0} Q ${mx} ${my}, ${x1} ${y1}`,
               label: sideways ? [top[0] + (nx > 0 ? 6 : -6), top[1] + 4] : [top[0], top[1] + (ny > 0 ? 14 : -6)],
               anchor: sideways ? (nx > 0 ? "start" : "end") : "middle" });
  }
  return out;
}

// ------------------------------------------------------------------ the direction, remembered per browser

const DIRECTION_KEY = "aip-console.graph-direction";

/** The graph direction the viewer last chose, kept in localStorage (best effort: private windows may refuse). */
export function useDirection(): [Direction, (d: Direction) => void] {
  const [direction, setDirection] = useState<Direction>(() => {
    try { return localStorage.getItem(DIRECTION_KEY) === "right" ? "right" : "down"; } catch { return "down"; }
  });
  const choose = (d: Direction) => {
    setDirection(d);
    try { localStorage.setItem(DIRECTION_KEY, d); } catch { /* the choice lasts the page */ }
  };
  return [direction, choose];
}

export function DirectionToggle({ direction, onChange }: { direction: Direction; onChange: (d: Direction) => void }) {
  return (
    <div className="direction-toggle" role="radiogroup" aria-label="direction" data-testid="direction">
      <label><input type="radio" name="direction" checked={direction === "down"} onChange={() => onChange("down")} /> down</label>
      <label><input type="radio" name="direction" checked={direction === "right"} onChange={() => onChange("right")} /> right</label>
    </div>
  );
}
