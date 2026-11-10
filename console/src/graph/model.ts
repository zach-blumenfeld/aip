// The step graph's model: a bundle's graph read as boxes and arrows. Steps are nodes, a `For` or a
// `Loop` is a frame around the nodes of its body, and the control edges of the bundle (`NEXT`,
// `BRANCH`, `BELOW`, `CONTINUES`, `AGAIN`, and `ENTERS` for the way into a body; aip
// docs/language/bundle.md) are the arrows. It is built on the card canvas's model, which already
// reads the graph's steps, loops and ways out, so the two views cannot disagree about a procedure.
// No DOM: it runs under node as it is (test/graph.test.ts).

import { modelOf, type Graph, type Model, type Port } from "../canvas/model.ts";

export type FlowKind = Port["kind"] | "enter";

/** One way from a node to another, as the procedure wrote it. */
export interface Way {
  kind: FlowKind;
  /** What the arrow is called: a branch's value, `< 0.6` for a confidence check, `continue`, `again`; empty for `next`. */
  label: string;
  line: number | null;
}

/** An arrow: every way from `from` to `to`, drawn as one line. A route whose `angry` branch and
 *  confidence check both lead to `escalate` is one arrow with two ways. */
export interface FlowEdge {
  /** `from->to`, over the graph's node ids. */
  key: string;
  from: string;
  to: string;
  ways: Way[];
  /** The target is a loop the source sits inside: the pass is over (`Continue`). */
  toFrame: boolean;
  /** From a loop to the first step of its body. */
  enter: boolean;
}

export interface StepNode {
  id: string;
  name: string;
  /** A step's kind, or `For` / `Loop` for a frame. */
  kind: string;
  frame: boolean;
  /** A step's description; a loop's header (`Until passed, At_Most 3, Else_Fail`). */
  title: string;
  /** The loop whose body holds it, or null at the top. */
  parent: string | null;
  /** A frame's body, in written order. */
  children: string[];
  line: number | null;
  endLine: number | null;
}

export interface StepGraph {
  name: string;
  nodes: Record<string, StepNode>;
  /** The ids outside every loop, in written order. */
  top: string[];
  edges: FlowEdge[];
  /** The card canvas's model of the same graph. */
  model: Model;
}

export const edgeKey = (from: string, to: string) => `${from}->${to}`;

/** Whether `inner` sits inside the loop `outer`, at any depth. */
export function inside(nodes: Record<string, StepNode>, inner: string, outer: string): boolean {
  let parent = nodes[inner]?.parent ?? null;
  for (let depth = 0; parent !== null && depth < 64; depth++) {
    if (parent === outer) return true;
    parent = nodes[parent]?.parent ?? null;
  }
  return false;
}

function labelOf(port: Port, toFrame: boolean): string {
  switch (port.kind) {
    case "next": return "";
    case "below": return `${port.label.replace(/^confidence below /, "< ")}${toFrame ? ": continue" : ""}`;
    case "branch": return toFrame ? `${port.label}: continue` : port.label;
    default: return port.kind;
  }
}

export function stepGraphOf(graph: Graph): StepGraph {
  const model = modelOf(graph);
  const nodes: Record<string, StepNode> = {};
  for (const card of Object.values(model.cards)) {
    nodes[card.id] = { id: card.id, name: card.name, kind: card.kind, frame: false, title: card.title, parent: card.parent,
                       children: [], line: card.line, endLine: card.endLine };
  }
  for (const frame of Object.values(model.frames)) {
    nodes[frame.id] = { id: frame.id, name: frame.name, kind: frame.kind, frame: true, title: frame.header, parent: frame.parent,
                        children: frame.children.filter((id) => id in model.cards || id in model.frames), line: frame.line, endLine: frame.endLine };
  }

  const edges = new Map<string, FlowEdge>();
  const add = (from: string, to: string, way: Way, enter = false) => {
    if (!(from in nodes) || !(to in nodes)) return;
    const key = edgeKey(from, to);
    let edge = edges.get(key);
    if (!edge) {
      edge = { key, from, to, ways: [], toFrame: inside(nodes, from, to), enter };
      edges.set(key, edge);
    }
    edge.ways.push(way);
  };
  for (const node of Object.values(nodes)) {
    if (node.frame && node.children.length > 0) add(node.id, node.children[0], { kind: "enter", label: "", line: node.line }, true);
    const ports = (model.cards[node.id] ?? model.frames[node.id]).ports;
    for (const port of ports) {
      const toFrame = port.target in nodes && inside(nodes, node.id, port.target);
      add(node.id, port.target, { kind: port.kind, label: labelOf(port, toFrame), line: port.line });
    }
  }
  return { name: model.name, nodes, top: model.top, edges: [...edges.values()], model };
}

/** An arrow's label: its ways' labels, the unnamed ones left out. */
export function edgeLabel(edge: FlowEdge): string {
  return edge.ways.map((w) => w.label).filter(Boolean).join(" · ");
}
