import { useMemo, useState } from "react";
import { START_INPUT } from "../graph/dataflow";
import { layout, type Direction } from "../graph/layout";
import type { Branch, Edge, StepDetail } from "../api/types";
import type { Traffic } from "./Traffic";
import type { Tier } from "../studio/lint";

const W = 150, H = 48, PAD = 24;
// Data-flow arrows run along the outside of the nodes (right of them top-down, below them left-to-right), one
// lane per arrow that skips a layer.
const LANE = 26, LANE_GAP = 20;
// Left to right, the layers sit closer: a horizontal edge's label needs no room above it.
const LAYER_GAP: Record<Direction, number> = { down: 70, right: 52 };

interface Props {
  steps: StepDetail[];
  edges: Edge[];
  branches: Branch[];
  start: string;
  end: string;
  /** Steps to highlight, for the run trace (I4). */
  visited?: Set<string>;
  /** Edges a run took, as `from->to`; without it, an edge between two visited steps counts as taken. */
  taken?: Set<string>;
  /** Draw the data flow instead: one arrow per (producer, consumer) labelled with the keys it carries
   *  (graph/dataflow.ts), with the start input as a node of its own. Control edges stay, faint. */
  flow?: { from: string; to: string; keys: string[] }[];
  /** Weight the control edges by the runs that took them and badge each step with the runs that reached it. */
  traffic?: Traffic;
  /** Layers top-down (the default) or left-to-right. */
  direction?: Direction;
  /** Studio: a node is a button that selects its step. Node ids are step ids; `labels` gives the text drawn. */
  onSelect?: (id: string) => void;
  selected?: string;
  labels?: Map<string, string>;
  /** Studio: the worst lint tier on each step, drawn as a marker on its node. */
  marks?: Map<string, Tier>;
}

export function StepGraph({ steps, edges, branches, start, end, visited, taken: takenEdges, flow, traffic, direction = "down", onSelect, selected, labels, marks }: Props) {
  const g = useMemo(() => {
    const all = [
      ...edges.map((e) => ({ from: e.from, to: e.to })),
      ...branches.map((b) => ({ from: b.router, to: b.to, label: b.value })),
    ];
    const nodes = steps.map((s) => ({ id: s.name }));
    const opts = { nodeWidth: W, nodeHeight: H, layerGap: LAYER_GAP[direction], direction };
    // The start input sits before the start step; its edge to the start is only there to place it.
    if (flow) return layout([{ id: START_INPUT }, ...nodes], [{ from: START_INPUT, to: start }, ...all], { ...opts, start: START_INPUT });
    return layout(nodes, all, { ...opts, start });
  }, [steps, edges, branches, start, flow, direction]);
  const byName = new Map(steps.map((s) => [s.name, s]));
  const data = useMemo(() => (flow ? route(flow, g.nodes, direction) : []), [flow, g, direction]);
  // Data lanes reach past the nodes along the order axis: the width top-down, the height left-to-right.
  const across = direction === "down" ? g.width : g.height;
  const extra = data.length ? Math.max(0, ...data.map((d) => d.reach - across)) + 8 : 0;
  const width = g.width + 2 * PAD + (direction === "down" ? extra : 0);
  const height = g.height + 2 * PAD + (direction === "right" ? extra : 0);
  const controlEdges = g.edges.filter((e) => e.from !== START_INPUT);
  const busiest = traffic ? Math.max(1, ...traffic.edges.values()) : 1;

  return (
    <svg
      className={`step-graph${flow ? " data-mode" : ""}${traffic ? " traffic-mode" : ""}`}
      role="img"
      aria-label="step graph"
      data-direction={direction}
      viewBox={`${-PAD} ${-PAD} ${width} ${height}`}
      width={width}
      height={height}
    >
      <defs>
        {/* userSpaceOnUse: the head stays this size however thick the traffic mode draws the line. */}
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
        </marker>
        <marker id="arrow-busy" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="10" markerHeight="10" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="busy-arrow" />
        </marker>
        <marker id="data-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="data-arrow" />
        </marker>
      </defs>
      {controlEdges.map((e) => {
        const d = e.points.map(([x, y], i) => `${i ? "L" : "M"} ${x} ${y}`).join(" ");
        const [mx, my] = midpoint(e.points);
        const taken = takenEdges ? takenEdges.has(`${e.from}->${e.to}`) : (visited?.has(e.from) && visited?.has(e.to));
        const runs = traffic ? (traffic.edges.get(`${e.from}->${e.to}`) ?? 0) : null;
        // Traffic: width grows with the square root of the share, so a rare branch still reads as a line.
        const width = runs !== null ? (runs ? 1.5 + 6 * Math.sqrt(runs / busiest) : 1) : taken ? 2.5 : 1.25;
        return (
          <g key={`${e.from}->${e.to}:${e.label ?? ""}`} className={`edge${taken ? " taken" : ""}${runs ? " busy" : runs === 0 ? " idle" : ""}`}
             data-testid="step-edge" data-from={e.from} data-to={e.to} data-taken={taken ? "true" : "false"}
             data-runs={runs ?? undefined}>
            <path d={d} fill="none" stroke="currentColor" strokeWidth={width} strokeLinejoin="round" markerEnd={runs ? "url(#arrow-busy)" : "url(#arrow)"} />
            {e.label && (
              <text x={mx} y={my - 4 - width / 2} textAnchor="middle" className="branch-label" data-testid="branch-label">
                {e.label}
              </text>
            )}
            {runs ? (direction === "down"
              ? <text x={mx + 9 + width / 2} y={my + 4} textAnchor="start" className="run-count" data-testid="edge-runs">{runs}</text>
              : <text x={mx} y={my + 13 + width / 2} textAnchor="middle" className="run-count" data-testid="edge-runs">{runs}</text>) : null}
          </g>
        );
      })}
      {data.map((d) => (
        <g key={`${d.from}=>${d.to}`} className="data-edge" data-testid="data-edge" data-from={d.from} data-to={d.to}
           data-keys={d.keys.join(",")}>
          <path d={d.path} fill="none" stroke="currentColor" strokeWidth={1.5} strokeDasharray="5 3" markerEnd="url(#data-arrow)" />
          <text x={d.label[0]} y={d.label[1]} textAnchor={d.anchor} className="data-label" data-testid="data-label">{d.keys.join(", ")}</text>
        </g>
      ))}
      {g.nodes.map((n) => {
        if (n.id === START_INPUT) {
          return (
            <g key={n.id} className="node input-node" transform={`translate(${n.x}, ${n.y})`} data-testid="input-node">
              <rect width={W} height={H} rx={H / 2} />
              <text x={W / 2} y={H / 2 + 5} textAnchor="middle" className="node-name">start input</text>
            </g>
          );
        }
        const step = byName.get(n.id)!;
        const isEnd = n.id === end, isStart = n.id === start;
        const text = labels?.get(n.id) ?? n.id;
        const mark = marks?.get(n.id);
        const node = (
            <g
              className={`node kind-${step.kind}${visited?.has(n.id) ? " visited" : ""}${selected === n.id ? " selected" : ""}`}
              transform={`translate(${n.x}, ${n.y})`}
              data-testid="step-node"
              data-step={n.id}
              data-name={text}
              data-kind={step.kind}
              {...(onSelect && { role: "button", tabIndex: 0, "aria-pressed": selected === n.id, "aria-label": `${text} (${step.kind})`,
                onClick: () => onSelect(n.id),
                onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(n.id); } } })}
            >
              <rect width={W} height={H} rx={step.kind === "router" ? H / 2 : 6} />
              {isEnd && <rect x={3} y={3} width={W - 6} height={H - 6} rx={4} className="end-ring" />}
              {isStart && <circle cx={0} cy={H / 2} r={5} className="start-dot" />}
              <text x={W / 2} y={H / 2 - 4} textAnchor="middle" className="node-name">{text}</text>
              <text x={W / 2} y={H / 2 + 13} textAnchor="middle" className="node-kind">{step.kind}</text>
              {traffic && <Badge runs={traffic.steps.get(n.id) ?? 0} failed={traffic.failed.get(n.id) ?? 0} total={traffic.runs} />}
              {mark && (
                <g className={`mark mark-${mark}`} data-testid="step-mark" data-tier={mark}>
                  <title>{mark}</title>
                  <circle cx={W - 2} cy={H - 2} r={6} />
                </g>
              )}
            </g>
        );
        return onSelect ? <g key={n.id} className="node-button">{node}</g> : <a key={n.id} href={`#step-${n.id}`} className="node-link">{node}</a>;
      })}
    </svg>
  );
}

/** The runs that reached a step, pinned to its top-right corner; red when some failed there. */
function Badge({ runs, failed, total }: { runs: number; failed: number; total: number }) {
  const text = failed ? `${runs} · ${failed} failed` : String(runs);
  const w = 8 + 6.5 * text.length;
  return (
    <g className={`badge${failed ? " failed" : runs ? "" : " none"}`} transform={`translate(${W - w + 8}, -9)`} data-testid="step-runs"
       data-runs={runs} data-failed={failed}>
      <title>{runs} of {total} runs reached this step{failed ? `, ${failed} failed here` : ""}</title>
      <rect width={w} height={18} rx={9} />
      <text x={w / 2} y={13} textAnchor="middle">{text}</text>
    </g>
  );
}

interface Routed { from: string; to: string; keys: string[]; path: string; label: [number, number]; anchor: "start" | "middle"; reach: number }

/** Paths for the data arrows, in the layout's (order, rank) terms: one to the next layer leaves the producer's
 *  rank-end side a little past the control edge; a longer one leaves its outer side and curves out to a lane
 *  of its own, so arrows that skip layers never cross a node. `reach` is how far along the order axis the
 *  arrow and its label go. */
function route(flow: { from: string; to: string; keys: string[] }[], nodes: { id: string; x: number; y: number; layer: number }[], direction: Direction): Routed[] {
  const down = direction === "down";
  const sizeO = down ? W : H, sizeR = down ? H : W;
  const O = (n: { x: number; y: number }) => (down ? n.x : n.y), R = (n: { x: number; y: number }) => (down ? n.y : n.x);
  const P = (o: number, r: number): [number, number] => (down ? [o, r] : [r, o]);
  const pt = (o: number, r: number) => P(o, r).join(" ");
  // A label's extent along the order axis: its length top-down, its height left-to-right.
  const labelReach = (o: number, keys: string[]) => o + (down ? textWidth(keys) : 12);
  const at = new Map(nodes.map((n) => [n.id, n]));
  const placed = flow.filter((f) => at.has(f.from) && at.has(f.to));
  const long = placed.filter((f) => at.get(f.to)!.layer - at.get(f.from)!.layer !== 1)
    .sort((a, b) => (at.get(a.to)!.layer - at.get(a.from)!.layer) - (at.get(b.to)!.layer - at.get(b.from)!.layer));
  return placed.map((f) => {
    const a = at.get(f.from)!, b = at.get(f.to)!;
    const lane = long.indexOf(f);
    if (lane < 0) {
      const o0 = O(a) + sizeO / 2 + 14, o1 = O(b) + sizeO / 2 + 14, r0 = R(a) + sizeR, r1 = R(b);
      const path = `M ${pt(o0, r0)} L ${pt(o1, r1)}`;
      // Top-down the label sits beside the arrow; left-to-right the gap is narrow, so it hangs below the nodes,
      // centred on the gap.
      if (down) {
        const lo = (o0 + o1) / 2 + 6;
        return { ...f, path, label: P(lo, (r0 + r1) / 2 + 4), anchor: "start", reach: labelReach(lo, f.keys) };
      }
      const lo = Math.max(O(a), O(b)) + sizeO + 12;
      return { ...f, path, label: P(lo, (r0 + r1) / 2), anchor: "middle", reach: labelReach(lo, f.keys) };
    }
    const o0 = O(a) + sizeO, r0 = R(a) + sizeR / 2 + 6, o1 = O(b) + sizeO, r1 = R(b) + sizeR / 2 - 6;
    const co = Math.max(o0, o1) + LANE + lane * LANE_GAP;
    const path = `M ${pt(o0, r0)} C ${pt(co, r0)}, ${pt(co, r1)}, ${pt(o1, r1)}`;
    const lo = 0.25 * o0 + 0.75 * co + 4;
    return { ...f, path, label: P(lo, (r0 + r1) / 2), anchor: "start", reach: Math.max(co, labelReach(lo, f.keys)) };
  });
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
    <label className="direction-toggle">
      <input type="checkbox" checked={direction === "right"} onChange={(e) => onChange(e.target.checked ? "right" : "down")} /> left to right
    </label>
  );
}

/** Roughly how wide a label of these keys draws at 11px. */
function textWidth(keys: string[]): number {
  return 6.5 * keys.join(", ").length;
}

function midpoint(points: [number, number][]): [number, number] {
  if (points.length === 2) {
    const [[x1, y1], [x2, y2]] = points;
    return [(x1 + x2) / 2, (y1 + y2) / 2];
  }
  // A bent edge: the middle of its middle segment, which runs through a slot no node occupies.
  const i = Math.floor(points.length / 2);
  const [[x1, y1], [x2, y2]] = [points[i - 1], points[i]];
  return [(x1 + x2) / 2, (y1 + y2) / 2];
}
