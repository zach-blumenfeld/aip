// The card canvas's model: a bundle's graph (the nodes and edges `aip compile --json` prints, which a
// server also hands back for a revision; aip docs/language/bundle.md) read as cards. One card per step,
// with its kind, its description as the title, what it reads and produces, and one port per way out;
// one frame per loop around the cards of its body. Nothing here knows the console or the DOM: the
// console's procedure page and the VS Code extension's preview draw the same model, and it runs under
// node as it is (test/canvas.test.ts).

export interface GraphNode { id: string; labels: string[]; properties: Record<string, unknown> }
export interface GraphEdge { type: string; start: string; end: string; properties: Record<string, unknown> }
export interface Graph { nodes: GraphNode[]; edges: GraphEdge[] }

/** A way out of a card or a frame. */
export interface Port {
  /** `next`: Next_Step, or a loop's exit line; `branch`: one value of a route; `below`: a route's
   *  Confidence_Below; `continue`: the pass is over. */
  kind: "next" | "branch" | "below" | "continue";
  /** What the port is called on the card: `next`, a branch's value, `confidence below 0.9`. */
  label: string;
  /** The id of the card or frame it leads to. */
  target: string;
  /** The target in the reader's words: the next step's description. */
  quote: string;
  /** The line of `procedure.aip` that wrote it, when the graph carries spans. */
  line: number | null;
  /** What the compiler says is wrong with it, when the canvas draws diagnostics (problems.ts). A port the
   *  compiler finds missing has a problem and an empty `target`. */
  problem?: string;
}

/** A titled list on a card: what it reads, asks, produces. */
export interface Section { label: string; rows: string[] }

export interface Card {
  id: string;
  name: string;
  /** `Start`, `Decide`, `Route`, `Aggregate`, `Execute`, `Task_Agent` or `End`. */
  kind: string;
  /** The step's description; its name when it has none. */
  title: string;
  sections: Section[];
  ports: Port[];
  /** The id of the loop whose body holds it, or null at the top. */
  parent: string | null;
  line: number | null;
  endLine: number | null;
  /** The compiler's messages about it, when the canvas draws diagnostics (problems.ts). */
  problems?: string[];
}

export interface Frame {
  id: string;
  name: string;
  kind: "For" | "Loop";
  /** The loop's header after its name: `Until check_summary.all_hold, At_Most 3, Else_Fail`. */
  header: string;
  /** The ids of the cards and frames of its body, in written order. */
  children: string[];
  ports: Port[];
  parent: string | null;
  line: number | null;
  endLine: number | null;
  problems?: string[];
}

export interface Model {
  name: string;
  description: string;
  cards: Record<string, Card>;
  frames: Record<string, Frame>;
  /** The ids of the cards and frames outside every loop, in written order. */
  top: string[];
}

const text = (v: unknown): string => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const list = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => String(x)) : []);

/** `key` or `key.field`. */
function dotted(name: string, field: unknown): string {
  return typeof field === "string" && field ? `${name}.${field}` : name;
}

/** A key with its type and labels: `tone: choice [angry, calm]`. */
function typed(name: string, node: GraphNode | undefined): string {
  const type = text(node?.properties.type);
  const labels = list(node?.properties.labels);
  return `${name}${type ? `: ${type}` : ""}${labels.length ? ` [${labels.join(", ")}]` : ""}`;
}

/** A condition's tail: ` == value`, ` With Confidence_Above 0.7`. */
function condition(p: Record<string, unknown>, operator: string, value: string, above: string): string {
  const op = text(p[operator]);
  const bar = p[above];
  return `${op ? ` ${op} ${text(p[value])}` : ""}${bar !== undefined && bar !== null ? ` With Confidence_Above ${text(bar)}` : ""}`;
}

/** The model of a graph. A graph with no `Procedure` node gives an empty model. */
export function modelOf(graph: Graph): Model {
  const nodes = new Map<string, GraphNode>(graph.nodes.map((n) => [n.id, n]));
  const from = (id: string, type: string) => graph.edges.filter((e) => e.start === id && e.type === type);
  const into = (id: string, type: string) => graph.edges.filter((e) => e.end === id && e.type === type);
  const lineOf = (e: GraphEdge) => num(e.properties.line) ?? Number.MAX_SAFE_INTEGER;
  const byLine = (a: GraphEdge, b: GraphEdge) => lineOf(a) - lineOf(b);
  const byOrder = (a: GraphEdge, b: GraphEdge) => (num(a.properties.order) ?? 0) - (num(b.properties.order) ?? 0);
  const nameOf = (id: string) => text(nodes.get(id)?.properties.name) || id.replace(/^[a-z]+:/, "");

  const parentOf = new Map<string, string>();
  for (const e of graph.edges) if (e.type === "CONTAINS") parentOf.set(e.end, e.start);

  /** A target in the reader's words. */
  const quoteOf = (id: string): string => {
    const node = nodes.get(id);
    if (!node) return id;
    if (node.labels.includes("Loop")) return `${text(node.properties.kind) === "For" ? "for" : "loop"} ${nameOf(id)}`;
    return text(node.properties.description) || nameOf(id);
  };

  const portsOf = (id: string): Port[] => {
    const ports: { edge: GraphEdge; port: Port }[] = [];
    const add = (edge: GraphEdge, kind: Port["kind"], label: string, quote?: string) =>
      ports.push({ edge, port: { kind, label, target: edge.end, quote: quote ?? quoteOf(edge.end), line: num(edge.properties.line) } });
    const nextPass = (loop: string) => `the next pass of ${nameOf(loop)}`;
    for (const e of from(id, "BELOW")) {
      const label = `confidence below ${text(e.properties.below)}`;
      if (e.properties.continues === true) add(e, "below", label, nextPass(e.end));
      else add(e, "below", label);
    }
    for (const e of from(id, "BRANCH")) {
      if (e.properties.continues === true) add(e, "branch", text(e.properties.value), nextPass(e.end));
      else add(e, "branch", text(e.properties.value));
    }
    for (const e of from(id, "NEXT")) add(e, "next", "next");
    for (const e of from(id, "CONTINUES")) add(e, "continue", "continue", nextPass(e.end));
    ports.sort((a, b) => byLine(a.edge, b.edge));
    return ports.map((p) => p.port);
  };

  const cards: Record<string, Card> = {};
  const frames: Record<string, Frame> = {};

  for (const node of graph.nodes) {
    const p = node.properties;
    if (node.labels.includes("Step")) {
      const kind = text(p.kind);
      const sections: Section[] = [];
      const push = (label: string, rows: string[]) => { if (rows.length) sections.push({ label, rows: [...new Set(rows)] }); };

      const reads = into(node.id, "READ_BY").slice().sort(byLine);
      push("reads", reads.filter((e) => e.properties.interpolated !== true).map((e) => dotted(nameOf(e.start), e.properties.field)));
      push("fills in", reads.filter((e) => e.properties.interpolated === true).map((e) => `{${dotted(nameOf(e.start), e.properties.field)}}`));
      if (kind === "Route") {
        const read = reads.find((e) => typeof e.properties.source === "string");
        if (read) push("routes on", [`${text(read.properties.source)} answer`]);
      }
      push("asks", from(node.id, "ASKS").slice().sort(byOrder).map((e) => typed(nameOf(e.end), nodes.get(e.end))));
      push("aggregates", from(node.id, "AGGREGATES").slice().sort(byOrder).map((e) => {
        const a = nodes.get(e.end)?.properties ?? {};
        const over = from(e.end, "OVER")[0];
        const source = text(a.source) || (over ? dotted(nameOf(over.end), over.properties.field) : "");
        return `${nameOf(e.end)}: ${text(a.mode)} ${source}${condition(a, "operator", "value", "confidence_above")}`;
      }));
      push("runs", from(node.id, "RUNS").map((e) => text(nodes.get(e.end)?.properties.path)));
      push("prompt", from(node.id, "PROMPTED_BY").map((e) => text(nodes.get(e.end)?.properties.path)));
      push("uses", from(node.id, "USES").slice().sort(byLine).map((e) => text(nodes.get(e.end)?.properties.path)));
      const produced = from(node.id, "PRODUCES").slice().sort(byLine).map((e) => typed(nameOf(e.end), nodes.get(e.end)));
      push(kind === "Start" ? "inputs" : "produces", produced);

      cards[node.id] = {
        id: node.id, name: text(p.name), kind, title: text(p.description) || text(p.name), sections,
        ports: portsOf(node.id), parent: parentOf.get(node.id) ?? null, line: num(p.line), endLine: num(p.end_line),
      };
    } else if (node.labels.includes("Loop")) {
      const kind = text(p.kind) === "For" ? "For" : "Loop";
      const parts: string[] = [];
      const over = from(node.id, "OVER")[0];
      if (over) parts.push(`Over ${dotted(nameOf(over.end), over.properties.field)}${p.item ? ` As ${text(p.item)}` : ""}`);
      if (p.until_answer) parts.push(`Until ${text(p.until_answer)}${condition(p, "until_operator", "until_value", "until_confidence_above")}`);
      if (p.times !== undefined && p.times !== null) parts.push(`${text(p.times)} Times`);
      if (p.at_most !== undefined && p.at_most !== null) parts.push(`At_Most ${text(p.at_most)}`);
      if (p.collect_key) parts.push(`Collect ${text(p.collect_key)}${p.collect_into ? ` Into ${text(p.collect_into)}` : ""}`);
      if (p.at_cap) parts.push(text(p.at_cap));
      frames[node.id] = {
        id: node.id, name: text(p.name), kind, header: parts.join(", "),
        children: from(node.id, "CONTAINS").slice().sort(byOrder).map((e) => e.end),
        ports: portsOf(node.id), parent: parentOf.get(node.id) ?? null, line: num(p.line), endLine: num(p.end_line),
      };
    }
  }

  const lineOfItem = (id: string) => (cards[id] ?? frames[id])?.line ?? Number.MAX_SAFE_INTEGER;
  const top = [...Object.keys(cards), ...Object.keys(frames)].filter((id) => !parentOf.has(id)).sort((a, b) => lineOfItem(a) - lineOfItem(b));
  const procedure = graph.nodes.find((n) => n.labels.includes("Procedure"));
  return { name: text(procedure?.properties.name), description: text(procedure?.properties.description), cards, frames, top };
}

/** Lines `first` to `last` (1-based, inclusive) of `source`: the slice a card or a frame was written as. */
export function sliceOf(source: string, first: number | null, last: number | null): { text: string; first: number } | null {
  if (first === null) return null;
  const lines = source.split("\n");
  const end = Math.min(last ?? first, lines.length);
  if (first < 1 || first > lines.length) return null;
  return { text: lines.slice(first - 1, end).join("\n"), first };
}
