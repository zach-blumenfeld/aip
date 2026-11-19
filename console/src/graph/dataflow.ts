// Key-level data flow, read off the bundle's graph (aip docs/language/bundle.md): a key goes from each
// node that produces it to every node that reads it. A step produces what its `PRODUCES` edges name
// (`Start` produces the procedure's inputs); a loop produces its `Collect Into` list and binds its
// item key for the steps of its body. A step reads what its `READ_BY` edges name, whole or one field
// of it, in a `Read` or by interpolation; a loop reads the list it runs over, the answer its `Until`
// watches, and the per-pass key it collects. A key may have several producers, on different paths.
// No DOM: it runs under node as it is (test/graph.test.ts).

import type { Graph, GraphEdge } from "./bundle.ts";

export interface KeyRead {
  /** The id of the step or loop that reads. */
  node: string;
  /** `tone` in `triage_decision.tone`; null when the key is read whole. */
  field: string | null;
  /** `read`: a `Read` line; `fills in`: a `{key}` in a question or prompt; `over`, `until`, `collects`: a loop's header. */
  how: "read" | "fills in" | "over" | "until" | "collects";
  /** On a route's read, whose answer steers it: `measured`, `scripted`, `agent`, `input` or `aggregated`. */
  source: string | null;
}

export interface DataKey {
  key: string;
  type: string | null;
  labels: string[];
  /** The ids of the steps and loops that produce it, in written order. */
  producers: string[];
  readers: KeyRead[];
}

/** One drawn arrow: the keys that go from one node to another. */
export interface DataEdge { from: string; to: string; keys: string[] }

const text = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const lineOf = (e: GraphEdge) => (typeof e.properties.line === "number" ? e.properties.line : Number.MAX_SAFE_INTEGER);

/** Every key of the procedure, in the order the graph lists them, with who produces and who reads it. */
export function dataKeys(graph: Graph): DataKey[] {
  const keys = new Map<string, DataKey>();
  for (const node of graph.nodes) {
    if (!node.labels.includes("Data")) continue;
    const labels = Array.isArray(node.properties.labels) ? node.properties.labels.map((l) => String(l)) : [];
    keys.set(node.id, { key: text(node.properties.name) ?? node.id.replace(/^data:/, ""), type: text(node.properties.type), labels, producers: [], readers: [] });
  }
  const produce = (data: string, node: string) => {
    const key = keys.get(data);
    if (key && !key.producers.includes(node)) key.producers.push(node);
  };
  const read = (data: string, r: KeyRead) => {
    const key = keys.get(data);
    if (key && !key.readers.some((x) => x.node === r.node && x.field === r.field && x.how === r.how)) key.readers.push(r);
  };
  for (const e of graph.edges.slice().sort((a, b) => lineOf(a) - lineOf(b))) {
    const field = text(e.properties.field);
    switch (e.type) {
      case "PRODUCES": case "BINDS": produce(e.end, e.start); break;
      case "READ_BY":
        read(e.start, { node: e.end, field, how: e.properties.interpolated === true ? "fills in" : "read", source: text(e.properties.source) });
        break;
      // An aggregation's `OVER` is its step's `READ_BY` already; a loop's is the list it runs over.
      case "OVER": if (e.start.startsWith("loop:")) read(e.end, { node: e.start, field, how: "over", source: null }); break;
      case "WATCHES": read(e.end, { node: e.start, field, how: "until", source: null }); break;
      case "COLLECTS": read(e.end, { node: e.start, field, how: "collects", source: null }); break;
    }
  }
  return [...keys.values()];
}

/** The arrows: one per (producer, reader) pair, with the keys it carries in order. A node that reads
 *  what it produced itself draws nothing. */
export function dataEdges(keys: DataKey[]): DataEdge[] {
  const edges = new Map<string, DataEdge>();
  for (const key of keys) {
    for (const from of key.producers) {
      for (const reader of key.readers) {
        if (reader.node === from) continue;
        const id = `${from}=>${reader.node}`;
        const edge = edges.get(id) ?? { from, to: reader.node, keys: [] };
        if (!edge.keys.includes(key.key)) edge.keys.push(key.key);
        edges.set(id, edge);
      }
    }
  }
  return [...edges.values()];
}
