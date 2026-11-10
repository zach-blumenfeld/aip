import { useMemo, useState, type KeyboardEvent } from "react";
import type { DataEdge } from "../graph/dataflow.ts";
import { depthOf, layoutOf, SIZE, type Box, type Direction, type GraphLayout } from "../graph/layout.ts";
import { edgeLabel, type StepGraph as Model } from "../graph/model.ts";
import type { RunPath, Traffic } from "../graph/traffic.ts";

const PAD = 24;
// Data-flow arrows curve out past the nodes they join (right of them top-down, below them
// left-to-right), each in a lane no arrow it overlaps has.
const LANE = 26, LANE_GAP = 20;

interface Props {
  graph: Model;
  /** Layers top-down, or left-to-right. */
  direction?: Direction;
  /** Draw the data flow too: one dashed arrow per (producer, reader) with the keys it carries. Control edges stay, faint. */
  flow?: DataEdge[];
  /** Weight the control edges by the runs that took them and badge each step with the runs that reached it. */
  traffic?: Traffic;
  /** One run: the steps it reached and the arrows it took drawn heavy, where it waits or failed marked. */
  path?: RunPath;
  /** A node or a frame's header is a button that selects it. */
  onSelect?: (id: string) => void;
  selected?: string | null;
  /** In data flow, the key whose arrows stand out; without one, the selected node's do. */
  focusKey?: string | null;
}

/** The step graph: steps as nodes with their kind, loops as frames around their bodies, the control
 *  edges as arrows with a route's branches labelled. */
export function StepGraph({ graph, direction = "down", flow, traffic, path, onSelect, selected, focusKey }: Props) {
  const g = useMemo(() => layoutOf(graph, direction), [graph, direction]);
  const data = useMemo(() => (flow ? routeData(flow, g, graph) : []), [flow, g, graph]);
  const down = direction === "down";
  // Data lanes reach past the nodes along the order axis: the width top-down, the height left-to-right.
  const across = down ? g.width : g.height;
  const extra = data.length ? Math.max(0, ...data.map((d) => d.reach - across)) + 8 : 0;
  const width = g.width + 2 * PAD + (down ? extra : 0);
  const height = g.height + 2 * PAD + (down ? 0 : extra);
  const busiest = traffic ? Math.max(1, ...traffic.edges.values()) : 1;
  const frames = Object.values(graph.nodes).filter((n) => n.frame).sort((a, b) => depthOf(graph, a.id) - depthOf(graph, b.id));
  const steps = Object.values(graph.nodes).filter((n) => !n.frame);
  const mode = flow ? "data" : traffic ? "traffic" : path ? "path" : "control";
  const pick = (id: string) => onSelect && {
    role: "button", tabIndex: 0, "aria-pressed": selected === id,
    onClick: () => onSelect(id),
    onKeyDown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(id); } },
  };

  return (
    <svg className={`step-graph ${mode}-mode`} role="img" aria-label="step graph" data-testid="step-graph" data-direction={direction} data-mode={mode}
         viewBox={`${-PAD} ${-PAD} ${width} ${height}`} width={width} height={height}>
      <defs>
        {/* userSpaceOnUse: the head stays this size however thick the line is drawn. */}
        <marker id="sg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="arrow-head" />
        </marker>
        <marker id="sg-arrow-busy" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="10" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="busy-arrow" />
        </marker>
        <marker id="sg-arrow-data" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="data-arrow" />
        </marker>
      </defs>

      {frames.map((frame) => {
        const box = g.boxes[frame.id];
        if (!box) return null;
        const reached = path?.visited.has(frame.id);
        const header = clip(frame.title, box.w - 24 - 7.2 * (frame.kind.length + frame.name.length + 2));
        return (
          <g key={frame.id} className={`frame${reached ? " visited" : ""}${selected === frame.id ? " selected" : ""}${path?.failed === frame.id ? " failed" : ""}`}
             data-testid="graph-frame" data-loop={frame.name} data-kind={frame.kind} data-visited={path ? String(!!reached) : undefined}
             data-runs={traffic ? traffic.nodes.get(frame.id) ?? 0 : undefined}>
            <title>{`${frame.kind} ${frame.name} ${frame.title}`}</title>
            <rect x={box.x} y={box.y} width={box.w} height={box.h} rx={8} />
            <text x={box.x + 10} y={box.y + 16} className="frame-head" {...pick(frame.id)}>
              <tspan className="frame-kind">{frame.kind}</tspan> <tspan className="frame-name">{frame.name}</tspan>
              {header && <tspan className="frame-header"> {header}</tspan>}
            </text>
            {traffic && <Badge x={box.x + box.w} y={box.y} runs={traffic.nodes.get(frame.id) ?? 0} failed={traffic.failed.get(frame.id) ?? 0} total={traffic.runs} />}
            {path?.failed === frame.id && <Mark x={box.x + box.w} y={box.y} kind="failed" />}
          </g>
        );
      })}

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
                  strokeDasharray={kinds === "below" ? "6 3" : undefined} markerEnd={runs ? "url(#sg-arrow-busy)" : "url(#sg-arrow)"} />
            {(label || count) && (
              <text x={e.label[0]} y={e.label[1] + 4} textAnchor="middle" className="branch-label">
                {label && <tspan data-testid="branch-label">{label}</tspan>}
                {count && <tspan className="run-count" data-testid={runs ? "edge-runs" : "edge-times"}>{label ? " " : ""}{count}</tspan>}
              </text>
            )}
          </g>
        );
      })}

      {data.map((d) => {
        // With a key or a node picked, the arrows that carry it, or touch it, stand out from the rest.
        const lit = focusKey ? d.keys.includes(focusKey) : selected ? d.from === selected || d.to === selected : null;
        return (
        <g key={`${d.from}=>${d.to}`} className={`data-edge${lit === true ? " lit" : lit === false ? " dim" : ""}`} data-testid="data-edge"
           data-from={graph.nodes[d.from].name} data-to={graph.nodes[d.to].name} data-keys={d.keys.join(",")} data-lit={lit === null ? undefined : String(lit)}>
          <path d={d.path} fill="none" stroke="currentColor" strokeWidth={1.5} strokeDasharray="5 3" markerEnd="url(#sg-arrow-data)" />
          <text x={d.label[0]} y={d.label[1]} textAnchor={d.anchor} className="data-label" data-testid="data-label">{d.keys.join(", ")}</text>
        </g>
        );
      })}

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

interface Routed extends DataEdge { path: string; label: [number, number]; anchor: "start" | "middle"; reach: number }

/** Paths for the data arrows, in the layout's (order, rank) terms. Between a loop and a step of its
 *  body the arrow is a short one across the frame's nearer wall; any other leaves the producer's
 *  outer side and curves out to a lane of its own, so arrows do not run through the nodes between.
 *  `reach` is how far along the order axis the arrow and its label go. */
function routeData(flow: DataEdge[], g: GraphLayout, graph: Model): Routed[] {
  const down = g.direction === "down";
  const rect = (b: Box) => (down ? { o: b.x, so: b.w, r: b.y, sr: b.h } : { o: b.y, so: b.h, r: b.x, sr: b.w });
  const P = (o: number, r: number): [number, number] => (down ? [o, r] : [r, o]);
  const pt = (o: number, r: number) => P(o, r).join(" ");
  const holds = (outer: string, inner: string) => {
    for (let p = graph.nodes[inner]?.parent ?? null, d = 0; p !== null && d < 64; p = graph.nodes[p]?.parent ?? null, d++) if (p === outer) return true;
    return false;
  };
  // A label's extent along the order axis: its length top-down, its height left-to-right.
  const labelReach = (o: number, keys: string[]) => o + (down ? 6.5 * keys.join(", ").length : 12);
  const placed = flow.filter((f) => g.boxes[f.from] && g.boxes[f.to]);

  const stepRects = Object.values(graph.nodes).filter((n) => !n.frame && g.boxes[n.id]).map((n) => rect(g.boxes[n.id]));
  const lanes: { from: number; to: number }[][] = [];
  const curved = placed.filter((f) => !holds(f.from, f.to) && !holds(f.to, f.from)).map((f) => {
    const a = rect(g.boxes[f.from]), b = rect(g.boxes[f.to]);
    // A frame gives and takes at its head.
    const ra = graph.nodes[f.from].frame ? a.r + 12 : a.r + a.sr / 2 + 6;
    const rb = graph.nodes[f.to].frame ? b.r + 12 : b.r + b.sr / 2 - 6;
    // The arc bulges past every step it passes on the way, and past a frame it starts or ends at.
    const from = Math.min(ra, rb), to = Math.max(ra, rb);
    const between = stepRects.filter((s) => s.r <= to && s.r + s.sr >= from).map((s) => s.o + s.so);
    return { f, o0: a.o + a.so, r0: ra, o1: b.o + b.so, r1: rb, clear: Math.max(a.o + a.so, b.o + b.so, ...between) };
  }).sort((x, y) => Math.abs(x.r1 - x.r0) - Math.abs(y.r1 - y.r0));

  const out: Routed[] = [];
  for (const c of curved) {
    // Shortest first, each in the first lane no arc it overlaps has: short arcs nest inside long ones.
    const from = Math.min(c.r0, c.r1) - 4, to = Math.max(c.r0, c.r1) + 4;
    let lane = lanes.findIndex((taken) => taken.every((t) => to < t.from || from > t.to));
    if (lane < 0) { lanes.push([]); lane = lanes.length - 1; }
    lanes[lane].push({ from, to });
    // A cubic's bulge is three quarters of the way from its ends to its control points.
    const apex = c.clear + LANE + lane * LANE_GAP;
    const co = (apex - 0.25 * (c.o0 + c.o1) / 2) / 0.75;
    out.push({ ...c.f, path: `M ${pt(c.o0, c.r0)} C ${pt(co, c.r0)}, ${pt(co, c.r1)}, ${pt(c.o1, c.r1)}`,
               label: P(apex + 4, (c.r0 + c.r1) / 2 + 4), anchor: "start", reach: Math.max(apex, labelReach(apex + 4, c.f.keys)) });
  }
  for (const f of placed) {
    const gives = holds(f.from, f.to);
    if (!gives && !holds(f.to, f.from)) continue;
    const frame = rect(g.boxes[gives ? f.from : f.to]), step = rect(g.boxes[gives ? f.to : f.from]);
    // The nearer wall; what the loop gives runs a little above what it takes.
    const low = step.o - frame.o <= frame.o + frame.so - (step.o + step.so);
    const wall = low ? frame.o : frame.o + frame.so, side = low ? step.o : step.o + step.so;
    const r = step.r + step.sr / 2 + (gives ? -9 : 9);
    out.push({ ...f, path: gives ? `M ${pt(wall, r)} L ${pt(side, r)}` : `M ${pt(side, r)} L ${pt(wall, r)}`,
               label: P((wall + side) / 2, r - 4), anchor: "middle", reach: 0 });
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
