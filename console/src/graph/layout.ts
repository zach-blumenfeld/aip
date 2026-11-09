// A small layered (Sugiyama-style) layout for step graphs. Procedures have a
// handful of steps, so a hand-rolled longest-path layering with one barycenter
// ordering pass draws them cleanly without a layout library. An edge that skips
// layers is routed through dummy nodes, so it bends around the steps between; a
// back edge (a loop) runs along a rail outside the steps it spans. The layout is
// computed along two abstract axes, rank (layer to layer) and order (across a
// layer), and mapped to the page at the end: top-down or left-to-right.

export interface GraphNode { id: string }
export interface GraphEdge { from: string; to: string; label?: string }

export interface PlacedNode extends GraphNode { x: number; y: number; layer: number }
export interface PlacedEdge extends GraphEdge { points: [number, number][]; back: boolean }
export interface Layout { nodes: PlacedNode[]; edges: PlacedEdge[]; width: number; height: number }

export type Direction = "down" | "right";

export interface LayoutOptions {
  nodeWidth: number;
  nodeHeight: number;
  layerGap: number;
  nodeGap: number;
  /** The slot an edge that skips a layer takes in each layer it crosses. */
  dummyWidth: number;
  /** How far outside the steps a loop's rail runs, and the step between two rails on one side. */
  railGap: number;
  start?: string;
  direction: Direction;
}

const DEFAULTS: LayoutOptions = { nodeWidth: 150, nodeHeight: 48, layerGap: 70, nodeGap: 36, dummyWidth: 16, railGap: 18, direction: "down" };

export function layout(nodes: GraphNode[], edges: GraphEdge[], opts: Partial<LayoutOptions> = {}): Layout {
  const o = { ...DEFAULTS, ...opts };
  // A node's extent along each axis: down, a layer is a row and a node is nodeWidth across it.
  const sizeO = o.direction === "down" ? o.nodeWidth : o.nodeHeight;
  const sizeR = o.direction === "down" ? o.nodeHeight : o.nodeWidth;
  const ids = nodes.map((n) => n.id);
  const out = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const e of edges) if (out.has(e.from) && out.has(e.to)) out.get(e.from)!.push(e.to);

  // Depth-first from the start (then any unvisited node) to find back edges, so a
  // procedure that loops still gets a finite layering.
  const back = new Set<string>();
  const state = new Map<string, 0 | 1 | 2>();
  const visit = (id: string) => {
    state.set(id, 1);
    for (const to of out.get(id)!) {
      const s = state.get(to) ?? 0;
      if (s === 1) back.add(`${id}->${to}`);
      else if (s === 0) visit(to);
    }
    state.set(id, 2);
  };
  const roots = [o.start, ...ids].filter((id): id is string => !!id && out.has(id));
  for (const id of roots) if (!state.has(id)) visit(id);

  // Longest-path layering over the forward edges.
  const layerOf = new Map<string, number>();
  const forwardIn = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const e of edges) {
    if (out.has(e.from) && out.has(e.to) && !back.has(`${e.from}->${e.to}`)) forwardIn.get(e.to)!.push(e.from);
  }
  const depth = (id: string): number => {
    const known = layerOf.get(id);
    if (known !== undefined) return known;
    layerOf.set(id, 0); // guards against anything the back-edge pass missed
    const d = Math.max(-1, ...forwardIn.get(id)!.map(depth)) + 1;
    layerOf.set(id, d);
    return d;
  };
  for (const id of ids) depth(id);

  // An edge that skips layers gets a slim dummy node in each layer it crosses, so it is ordered and placed
  // like a node and never drawn through one; the drawn edge bends at each dummy.
  const sizeOf = new Map<string, number>(ids.map((id) => [id, sizeO]));
  const chains = new Map<string, string[]>();     // `from->to` of a long edge -> its dummies, top to bottom
  for (const e of edges) {
    const key = `${e.from}->${e.to}`;
    if (!out.has(e.from) || !out.has(e.to) || back.has(key) || chains.has(key)) continue;
    const span = layerOf.get(e.to)! - layerOf.get(e.from)!;
    if (span <= 1) continue;
    const dummies: string[] = [];
    let previous = e.from;
    for (let k = 1; k < span; k++) {
      const id = `\u0000${key}#${k}`;
      dummies.push(id);
      layerOf.set(id, layerOf.get(e.from)! + k);
      sizeOf.set(id, o.dummyWidth);
      forwardIn.set(id, [previous]);
      previous = id;
    }
    forwardIn.set(e.to, forwardIn.get(e.to)!.map((p) => (p === e.from ? previous : p)));
    chains.set(key, dummies);
  }
  const all = [...ids, ...[...chains.values()].flat()];

  // Order within a layer by the mean position of predecessors (one top-down pass),
  // ties broken by declaration order.
  const layers: string[][] = [];
  for (const id of all) (layers[layerOf.get(id)!] ??= []).push(id);
  const pos = new Map<string, number>();
  layers.forEach((layer, i) => {
    if (i > 0) {
      const bary = (id: string) => {
        const preds = forwardIn.get(id)!.map((p) => pos.get(p)!).filter((v) => v !== undefined);
        return preds.length ? preds.reduce((a, b) => a + b, 0) / preds.length : Number.POSITIVE_INFINITY;
      };
      layer.sort((a, b) => bary(a) - bary(b) || all.indexOf(a) - all.indexOf(b));
    }
    layer.forEach((id, j) => pos.set(id, j));
  });

  // Placement in (order, rank) coordinates: each layer centred across the widest.
  const rowWidth = (layer: string[]) => layer.reduce((w, id) => w + sizeOf.get(id)!, 0) + (layer.length - 1) * o.nodeGap;
  const extentO = Math.max(...layers.map(rowWidth));
  const placed = new Map<string, { o: number; r: number; layer: number }>();
  layers.forEach((layer, i) => {
    let at = (extentO - rowWidth(layer)) / 2;
    for (const id of layer) {
      placed.set(id, { o: at, r: i * (sizeR + o.layerGap), layer: i });
      at += sizeOf.get(id)! + o.nodeGap;
    }
  });
  const centre = (id: string) => placed.get(id)!.o + sizeOf.get(id)! / 2;

  // A loop's rail runs just outside every node and dummy in the layers it spans, on whichever side is nearer
  // to both ends; rails on one side are staggered.
  const lanes = { low: 0, high: 0 };
  const abstractEdges = edges
    .filter((e) => placed.has(e.from) && placed.has(e.to))
    .map((e) => {
      const a = placed.get(e.from)!, b = placed.get(e.to)!;
      const key = `${e.from}->${e.to}`;
      const isBack = back.has(key);
      const ao = centre(e.from), bo = centre(e.to);
      let points: [number, number][];
      if (isBack) {
        const spanned = layers.slice(Math.min(a.layer, b.layer), Math.max(a.layer, b.layer) + 1).flat();
        const low = Math.min(...spanned.map((id) => placed.get(id)!.o));
        const high = Math.max(...spanned.map((id) => placed.get(id)!.o + sizeOf.get(id)!));
        const nearerLow = (ao - low) + (bo - low) <= (high - ao) + (high - bo);
        const rail = nearerLow ? low - o.railGap * (1 + lanes.low++) : high + o.railGap * (1 + lanes.high++);
        const exit = nearerLow ? a.o : a.o + sizeO;
        const above = b.r - o.layerGap / 2;
        points = [[exit, a.r + sizeR / 2], [rail, a.r + sizeR / 2], [rail, above], [bo, above], [bo, b.r]];
      } else {
        points = [[ao, a.r + sizeR]];
        for (const d of chains.get(key) ?? []) {
          const at = placed.get(d)!;
          points.push([centre(d), at.r], [centre(d), at.r + sizeR]);
        }
        points.push([bo, b.r]);
      }
      return { ...e, points, back: isBack };
    });

  // The box holds every node and every edge point (rails and loops reach outside the layers).
  let minO = 0, maxO = extentO, minR = 0, maxR = layers.length * sizeR + (layers.length - 1) * o.layerGap;
  for (const e of abstractEdges) for (const [po, pr] of e.points) {
    minO = Math.min(minO, po); maxO = Math.max(maxO, po); minR = Math.min(minR, pr); maxR = Math.max(maxR, pr);
  }
  const map = (po: number, pr: number): [number, number] =>
    o.direction === "down" ? [po - minO, pr - minR] : [pr - minR, po - minO];
  const [width, height] = map(maxO, maxR);

  return {
    nodes: ids.map((id) => { const p = placed.get(id)!; const [x, y] = map(p.o, p.r); return { id, x, y, layer: p.layer }; }),
    edges: abstractEdges.map((e) => ({ ...e, points: e.points.map(([po, pr]) => map(po, pr)) })),
    width,
    height,
  };
}
