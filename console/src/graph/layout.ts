// Where the step graph's nodes, frames and arrows go. A small layered (Sugiyama-style) layout, done
// once per level: the top of the procedure, then the body of each loop, innermost first, so that a
// loop is a frame of known size by the time the level around it is laid out, and a frame is placed
// like any other node. Within a level: longest-path layering, one barycentre ordering pass, an edge
// that skips layers bent through a slot of its own in each layer it crosses, and an edge that goes
// back (`Again`) run along a rail outside the layers it spans. An edge that ends the pass
// (`Continue`) runs along a rail inside its loop's frame, back to the frame's head.
//
// Everything is computed along two abstract axes, rank (layer to layer) and order (across a layer),
// and mapped to the page at the end: top-down or left-to-right. No DOM and no imports but the
// model: it runs under node as it is (test/graph.test.ts).

import type { FlowEdge, StepGraph } from "./model.ts";

export type Direction = "down" | "right";

export const SIZE = {
  nodeWidth: 150,
  nodeHeight: 48,
  nodeGap: 36,        // between the nodes of a layer
  dummy: 16,          // the slot an edge that skips a layer takes in each layer it crosses
  rail: 18,           // from the nodes to the first rail, and between rails
  head: 24,           // a frame's header
  pad: 20,            // a frame's body from its sides
};
/** Between layers. Left to right an arrow's label sits on the arrow, so the layers stand further apart. */
const LAYER_GAP: Record<Direction, number> = { down: 64, right: 96 };

export interface Box { x: number; y: number; w: number; h: number }

export interface PlacedEdge {
  edge: FlowEdge;
  points: [number, number][];
  /** It runs along a rail: an edge back to an earlier step, or one that ends a loop's pass. */
  rail: boolean;
  /** Where its label is centred. */
  label: [number, number];
}

export interface GraphLayout {
  direction: Direction;
  boxes: Record<string, Box>;
  edges: PlacedEdge[];
  width: number;
  height: number;
}

interface Rect { o: number; r: number; so: number; sr: number }
interface Bend { o: number; r0: number; r1: number }

/** One level, laid out in its own coordinates. Rails, bends and back edges are keyed by the real edge's key. */
interface Level {
  ids: string[];
  at: Map<string, { o: number; r: number }>;
  size: Map<string, { so: number; sr: number }>;
  inner: Map<string, Level>;
  rails: Map<string, { o: number; side: "low" | "high" }>;
  bends: Map<string, Bend[]>;
  backs: Set<string>;
  box: { minO: number; maxO: number; minR: number; maxR: number };
}

export function layoutOf(graph: StepGraph, direction: Direction = "down"): GraphLayout {
  const down = direction === "down";
  const gap = LAYER_GAP[direction];
  const stepSize = down ? { so: SIZE.nodeWidth, sr: SIZE.nodeHeight } : { so: SIZE.nodeHeight, sr: SIZE.nodeWidth };
  // A frame's header runs along the top of the page: the start of the rank axis top-down, the low
  // end of the order axis left-to-right.
  const pads = down
    ? { start: SIZE.head + SIZE.pad, end: SIZE.pad, low: SIZE.pad, high: SIZE.pad }
    : { start: SIZE.pad, end: SIZE.pad, low: SIZE.head + SIZE.pad, high: SIZE.pad };
  const headR = down ? SIZE.head : 0;

  const level = (container: string | null): Level => {
    const ids = container === null ? graph.top : graph.nodes[container].children;
    const inner = new Map<string, Level>();
    const size = new Map<string, { so: number; sr: number }>();
    for (const id of ids) {
      if (!graph.nodes[id].frame) { size.set(id, stepSize); continue; }
      const body = level(id);
      inner.set(id, body);
      size.set(id, { so: body.box.maxO - body.box.minO + pads.low + pads.high, sr: body.box.maxR - body.box.minR + pads.start + pads.end });
    }

    /** The node of this level that is, or holds, `id`. */
    const childOf = (id: string): string | null => {
      let current: string | null = id;
      for (let depth = 0; current !== null && depth < 64; depth++) {
        const parent: string | null = graph.nodes[current]?.parent ?? null;
        if (parent === container) return current;
        current = parent;
      }
      return null;
    };

    const lifted: { edge: FlowEdge; a: string; b: string }[] = [];
    const ending: { edge: FlowEdge; a: string }[] = [];
    for (const edge of graph.edges) {
      if (edge.enter) continue;
      if (edge.toFrame) {
        const a = edge.to === container ? childOf(edge.from) : null;
        if (a) ending.push({ edge, a });
        continue;
      }
      const a = childOf(edge.from), b = childOf(edge.to);
      if (a && b && a !== b) lifted.push({ edge, a, b });
    }
    const pair = (a: string, b: string) => `${a}->${b}`;

    const out = new Map<string, string[]>(ids.map((id) => [id, []]));
    for (const l of lifted) if (!out.get(l.a)!.includes(l.b)) out.get(l.a)!.push(l.b);

    // Depth-first from the entry (then anything it does not reach) to find the edges that go back.
    const back = new Set<string>();
    const state = new Map<string, 1 | 2>();
    const visit = (id: string) => {
      state.set(id, 1);
      for (const to of out.get(id)!) {
        const s = state.get(to);
        if (s === 1) back.add(pair(id, to));
        else if (s === undefined) visit(to);
      }
      state.set(id, 2);
    };
    const entry = container === null ? ids.find((id) => graph.nodes[id].kind === "Start") : ids[0];
    for (const id of [entry, ...ids]) if (id !== undefined && !state.has(id)) visit(id);

    // Longest-path layering over the forward edges.
    const layerOf = new Map<string, number>();
    const forwardIn = new Map<string, string[]>(ids.map((id) => [id, []]));
    for (const l of lifted) if (!back.has(pair(l.a, l.b)) && !forwardIn.get(l.b)!.includes(l.a)) forwardIn.get(l.b)!.push(l.a);
    const depth = (id: string): number => {
      const known = layerOf.get(id);
      if (known !== undefined) return known;
      layerOf.set(id, 0);
      const d = Math.max(-1, ...forwardIn.get(id)!.map(depth)) + 1;
      layerOf.set(id, d);
      return d;
    };
    for (const id of ids) depth(id);

    // An edge that skips layers gets a slim slot in each layer it crosses, ordered and placed like a node.
    const sizeO = new Map<string, number>(ids.map((id) => [id, size.get(id)!.so]));
    const chains = new Map<string, string[]>();
    for (const l of lifted) {
      const key = pair(l.a, l.b);
      if (back.has(key) || chains.has(key)) continue;
      const span = layerOf.get(l.b)! - layerOf.get(l.a)!;
      if (span <= 1) continue;
      const dummies: string[] = [];
      let previous = l.a;
      for (let k = 1; k < span; k++) {
        const id = `\u0000${key}#${k}`;
        dummies.push(id);
        layerOf.set(id, layerOf.get(l.a)! + k);
        sizeO.set(id, SIZE.dummy);
        forwardIn.set(id, [previous]);
        previous = id;
      }
      forwardIn.set(l.b, forwardIn.get(l.b)!.map((p) => (p === l.a ? previous : p)));
      chains.set(key, dummies);
    }
    const all = [...ids, ...[...chains.values()].flat()];

    // Order within a layer by the mean position of its predecessors, ties in written order.
    const layers: string[][] = [];
    for (const id of all) (layers[layerOf.get(id)!] ??= []).push(id);
    const position = new Map<string, number>();
    layers.forEach((layer, i) => {
      if (i > 0) {
        const bary = (id: string) => {
          const preds = forwardIn.get(id)!.map((p) => position.get(p)).filter((v): v is number => v !== undefined);
          return preds.length ? preds.reduce((a, b) => a + b, 0) / preds.length : Number.POSITIVE_INFINITY;
        };
        layer.sort((a, b) => bary(a) - bary(b) || all.indexOf(a) - all.indexOf(b));
      }
      layer.forEach((id, j) => position.set(id, j));
    });

    // Placement: a layer is as deep as its deepest node, and is centred across the widest layer.
    const layerSize = layers.map((layer) => Math.max(0, ...layer.map((id) => size.get(id)?.sr ?? 0)));
    const layerR: number[] = [];
    layers.forEach((_, i) => { layerR[i] = i === 0 ? 0 : layerR[i - 1] + layerSize[i - 1] + gap; });
    const rowWidth = (layer: string[]) => layer.reduce((w, id) => w + sizeO.get(id)!, 0) + (layer.length - 1) * SIZE.nodeGap;
    const extentO = Math.max(0, ...layers.map(rowWidth));
    const placed = new Map<string, { o: number; r: number; layer: number }>();
    layers.forEach((layer, i) => {
      let o = (extentO - rowWidth(layer)) / 2;
      for (const id of layer) {
        placed.set(id, { o, r: layerR[i], layer: i });
        o += sizeO.get(id)! + SIZE.nodeGap;
      }
    });

    // Rails: just outside every node and slot of the layers an edge spans; the rails of one side are staggered.
    const lanes = { low: 0, high: 0 };
    const railAt = (from: number, to: number, side: "low" | "high") => {
      const spanned = layers.slice(Math.min(from, to), Math.max(from, to) + 1).flat();
      return side === "low"
        ? Math.min(...spanned.map((id) => placed.get(id)!.o)) - SIZE.rail * (1 + lanes.low++)
        : Math.max(...spanned.map((id) => placed.get(id)!.o + sizeO.get(id)!)) + SIZE.rail * (1 + lanes.high++);
    };
    const rails = new Map<string, { o: number; side: "low" | "high" }>();
    const bends = new Map<string, Bend[]>();
    const backs = new Set<string>();
    let minR = 0;
    for (const l of lifted) {
      const key = pair(l.a, l.b);
      if (back.has(key)) {
        const a = placed.get(l.a)!, b = placed.get(l.b)!;
        backs.add(l.edge.key);
        rails.set(l.edge.key, { o: railAt(a.layer, b.layer, "low"), side: "low" });
        if (b.layer === 0) minR = -gap / 2;
      } else if (chains.has(key)) {
        bends.set(l.edge.key, chains.get(key)!.map((d) => {
          const p = placed.get(d)!;
          return { o: p.o + SIZE.dummy / 2, r0: p.r, r1: p.r + layerSize[p.layer] };
        }));
      }
    }
    for (const { edge, a } of ending) {
      const p = placed.get(a)!;
      const beside = layers[p.layer].filter((id) => id !== a).map((id) => placed.get(id)!.o);
      // The side nothing stands on, the high one when both are free or both taken.
      const side = beside.some((o) => o > p.o) && !beside.some((o) => o < p.o) ? "low" : "high";
      rails.set(edge.key, { o: railAt(0, p.layer, side), side });
    }

    const railOs = [...rails.values()].map((r) => r.o);
    const at = new Map<string, { o: number; r: number }>(ids.map((id) => [id, placed.get(id)!]));
    return {
      ids, at, size, inner, rails, bends, backs,
      box: { minO: Math.min(0, ...railOs), maxO: Math.max(extentO, ...railOs), minR,
             maxR: layers.length ? layerR[layers.length - 1] + layerSize[layers.length - 1] : 0 },
    };
  };

  // Every level in the picture's coordinates.
  const rects = new Map<string, Rect>();
  const rails = new Map<string, { o: number; side: "low" | "high" }>();
  const bends = new Map<string, Bend[]>();
  const backs = new Set<string>();
  const settle = (lv: Level, originO: number, originR: number) => {
    for (const id of lv.ids) {
      const p = lv.at.get(id)!, s = lv.size.get(id)!;
      rects.set(id, { o: originO + p.o, r: originR + p.r, so: s.so, sr: s.sr });
      const body = lv.inner.get(id);
      if (body) settle(body, originO + p.o + pads.low - body.box.minO, originR + p.r + pads.start - body.box.minR);
    }
    for (const [key, rail] of lv.rails) rails.set(key, { o: originO + rail.o, side: rail.side });
    for (const [key, list] of lv.bends) bends.set(key, list.map((b) => ({ o: originO + b.o, r0: originR + b.r0, r1: originR + b.r1 })));
    for (const key of lv.backs) backs.add(key);
  };
  const top = level(null);
  settle(top, -top.box.minO, -top.box.minR);

  const page = (o: number, r: number): [number, number] => (down ? [o, r] : [r, o]);
  const middle = (a: [number, number], b: [number, number]): [number, number] => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];

  const edges: PlacedEdge[] = [];
  for (const edge of graph.edges) {
    const a = rects.get(edge.from), b = rects.get(edge.to);
    if (!a || !b) continue;
    const rail = rails.get(edge.key);
    let points: [number, number][];
    let label: [number, number];
    if (edge.enter) {
      // From the frame's head to the first step of its body.
      const o = b.o + b.so / 2;
      points = [page(o, a.r + headR), page(o, b.r)];
      label = middle(points[0], points[1]);
    } else if (edge.toFrame && rail) {
      // The pass is over: out of the step's side, along the rail, back to the frame's head.
      const exit = rail.side === "low" ? a.o : a.o + a.so;
      points = [page(exit, a.r + a.sr / 2), page(rail.o, a.r + a.sr / 2), page(rail.o, b.r + headR)];
      label = middle(points[1], points[2]);
    } else if (backs.has(edge.key) && rail) {
      const above = b.r - gap / 2;
      const arrive = b.o + b.so / 4;
      points = [page(a.o, a.r + a.sr / 2), page(rail.o, a.r + a.sr / 2), page(rail.o, above), page(arrive, above), page(arrive, b.r)];
      label = middle(points[1], points[2]);
    } else {
      points = [page(a.o + a.so / 2, a.r + a.sr)];
      for (const bend of bends.get(edge.key) ?? []) points.push(page(bend.o, bend.r0), page(bend.o, bend.r1));
      points.push(page(b.o + b.so / 2, b.r));
      // A bent edge is labelled on its middle segment, which runs through a slot no node occupies.
      const i = points.length === 2 ? 1 : Math.floor(points.length / 2);
      label = middle(points[i - 1], points[i]);
    }
    edges.push({ edge, points, rail: rail !== undefined && !edge.enter, label });
  }

  const boxes: Record<string, Box> = {};
  for (const [id, rect] of rects) {
    const [x, y] = page(rect.o, rect.r);
    boxes[id] = down ? { x, y, w: rect.so, h: rect.sr } : { x, y, w: rect.sr, h: rect.so };
  }
  const [width, height] = page(top.box.maxO - top.box.minO, top.box.maxR - top.box.minR);
  return { direction, boxes, edges, width, height };
}

/** How deep a node sits: 0 at the top, 1 inside one loop. Frames are drawn outermost first. */
export function depthOf(graph: StepGraph, id: string): number {
  let depth = 0;
  let parent = graph.nodes[id]?.parent ?? null;
  while (parent !== null && depth < 64) {
    depth += 1;
    parent = graph.nodes[parent]?.parent ?? null;
  }
  return depth;
}
