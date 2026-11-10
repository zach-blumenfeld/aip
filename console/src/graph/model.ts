// The step graph's model: a bundle's graph read as boxes and arrows, shaped the way the bundle is
// (aip docs/language/queries.md, "Control flow"). Steps are nodes and a `For` or a `Loop` is a node
// of its own; the control edges of the bundle are the arrows: `NEXT`, `BRANCH`, `BELOW`, `ENTERS`
// from a loop to the first step of its body, `CONTINUES` from the body back to its loop,
// and a loop's exit line from the loop to the step after it. `CONTAINS` is membership, not flow: it
// says whose body a node is in and draws nothing. It is built on the card canvas's model, which
// already reads the graph's steps, loops and ways out, so the two views cannot disagree about a
// procedure. No DOM: it runs under node as it is (test/graph.test.ts).

import { modelOf, type Graph, type Model, type Port } from "./bundle.ts";

export type FlowKind = Port["kind"] | "enter";

/** One way from a node to another, as the procedure wrote it. */
export interface Way {
  kind: FlowKind;
  /** What the arrow is called: a branch's value, `< 0.6` for a confidence check, `continue`; empty for `next`. */
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
  toLoop: boolean;
  /** From a loop to the first step of its body. */
  enter: boolean;
}

export interface StepNode {
  id: string;
  name: string;
  /** A step's kind, or `For` / `Loop`. */
  kind: string;
  loop: boolean;
  /** A step's description; a loop's header (`Until passed, At_Most 3, Else_Fail`). */
  title: string;
  /** What a loop node says under its name: `Over tickets, At_Most 50`, `Until passed, At_Most 3`. Empty for a step. */
  summary: string;
  /** The loop whose body holds it, or null at the top. */
  parent: string | null;
  /** A loop's body, in written order. */
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

function labelOf(port: Port, toLoop: boolean): string {
  switch (port.kind) {
    case "next": return "";
    case "below": return `${port.label.replace(/^confidence below /, "< ")}${toLoop ? ": continue" : ""}`;
    case "branch": return toLoop ? `${port.label}: continue` : port.label;
    default: return port.kind;
  }
}

/** A loop in one line: what it runs over or until, and its cap. The rest of its header (`As`,
 *  `Collect ... Into`, `Else_Fail`) is in `title`. */
function summaryOf(graph: Graph, id: string): string {
  const p = graph.nodes.find((n) => n.id === id)?.properties ?? {};
  const text = (v: unknown) => (v === undefined || v === null ? "" : String(v));
  const parts: string[] = [];
  const over = graph.edges.find((e) => e.start === id && e.type === "OVER");
  if (over) {
    const list = graph.nodes.find((n) => n.id === over.end)?.properties.name;
    const field = over.properties.field;
    parts.push(`Over ${text(list) || over.end.replace(/^[a-z]+:/, "")}${typeof field === "string" && field ? `.${field}` : ""}`);
  }
  if (p.until_answer) parts.push(`Until ${text(p.until_answer)}${p.until_operator ? ` ${text(p.until_operator)} ${text(p.until_value)}` : ""}`);
  if (text(p.times)) parts.push(`${text(p.times)} Times`);
  if (text(p.at_most)) parts.push(`At_Most ${text(p.at_most)}`);
  return parts.join(", ");
}

export function stepGraphOf(graph: Graph): StepGraph {
  const model = modelOf(graph);
  const nodes: Record<string, StepNode> = {};
  for (const card of Object.values(model.cards)) {
    nodes[card.id] = { id: card.id, name: card.name, kind: card.kind, loop: false, title: card.title, summary: "", parent: card.parent,
                       children: [], line: card.line, endLine: card.endLine };
  }
  for (const frame of Object.values(model.frames)) {
    nodes[frame.id] = { id: frame.id, name: frame.name, kind: frame.kind, loop: true, title: frame.header, summary: summaryOf(graph, frame.id),
                        parent: frame.parent, children: frame.children.filter((id) => id in model.cards || id in model.frames),
                        line: frame.line, endLine: frame.endLine };
  }

  const edges = new Map<string, FlowEdge>();
  const add = (from: string, to: string, way: Way, enter = false) => {
    if (!(from in nodes) || !(to in nodes)) return;
    const key = edgeKey(from, to);
    let edge = edges.get(key);
    if (!edge) {
      edge = { key, from, to, ways: [], toLoop: inside(nodes, from, to), enter };
      edges.set(key, edge);
    }
    edge.ways.push(way);
  };
  for (const node of Object.values(nodes)) {
    if (node.loop && node.children.length > 0) add(node.id, node.children[0], { kind: "enter", label: "", line: node.line }, true);
    const ports = (model.cards[node.id] ?? model.frames[node.id]).ports;
    for (const port of ports) {
      const toLoop = port.target in nodes && inside(nodes, node.id, port.target);
      add(node.id, port.target, { kind: port.kind, label: labelOf(port, toLoop), line: port.line });
    }
  }
  return { name: model.name, nodes, top: model.top, edges: [...edges.values()], model };
}

/** An arrow's label: its ways' labels, the unnamed ones left out. */
export function edgeLabel(edge: FlowEdge): string {
  return edge.ways.map((w) => w.label).filter(Boolean).join(" · ");
}
