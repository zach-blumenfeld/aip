// Where the step graph's nodes and arrows go. A loop is a node, and its body hangs beside it like an
// indented block: the steps of one level (the top of the procedure, or one loop's body) run straight
// along that level's axis, a loop's body starts beside the loop node and runs along an axis of its
// own, and the loop's exit carries on along the axis the loop stands on, past the whole body. So the
// way in (`ENTERS`) is a short arrow from the loop node across to the first step of its body, and
// `Continue` comes back to the loop node along a rail in the gutter between the two: the loop reads
// as a cycle, and a nested loop is a cycle hung off a step of another.
//
// Each level is a small layered (Sugiyama-style) layout, innermost first, so that a loop with its
// body is a block of known size by the time the level around it is laid out: longest-path layering,
// one barycentre ordering pass, an edge that skips layers bent through a slot of its own in each
// layer it crosses. Nothing goes back but `Continue`, to the loop: every cycle is a loop node.
//
// Everything is computed along two abstract axes, rank (layer to layer) and order (across a layer),
// and mapped to the page at the end: top-down (bodies to the right of their loops) or left-to-right
// (bodies below them). No DOM and no imports but the model: it runs under node as it is
// (test/graph.test.ts).

import type { FlowEdge, StepGraph } from "./model.ts";

export type Direction = "down" | "right";

export const SIZE = {
  nodeWidth: 150,
  nodeHeight: 48,
  loopHeight: 64,     // a loop node has a third line, its summary
  loopWidest: 280,    // a loop node is as wide as its summary, up to this
  nodeGap: 36,        // between the nodes of a layer
  dummy: 16,          // the slot an edge that skips a layer takes in each layer it crosses
  rail: 20,           // from the nodes to the first rail, and between rails
  gutter: 44,         // from a loop node to its body's nearest rail or node
};
/** Between layers. Left to right an arrow's label sits on the arrow, so the layers stand further apart. */
const LAYER_GAP: Record<Direction, number> = { down: 56, right: 88 };

export interface Box { x: number; y: number; w: number; h: number }

export interface PlacedEdge {
  edge: FlowEdge;
  points: [number, number][];
  /** It goes back: `Continue`, to its loop. */
  rail: boolean;
  /** Where its label goes, and which end of the text that point is. */
  label: [number, number];
  anchor: "start" | "middle" | "end";
}

export interface GraphLayout {
  direction: Direction;
  boxes: Record<string, Box>;
  edges: PlacedEdge[];
  width: number;
  height: number;
}

interface Rect { o: number; r: number; so: number; sr: number }
type Point = [number, number];
interface Route { edge: FlowEdge; rail: boolean; points: Point[]; label: Point; anchor: PlacedEdge["anchor"] }

/** One level, laid out around its own axis (order 0); `settle` puts it, and the levels inside it, on the page. */
interface Level {
  minO: number;
  maxO: number;
  maxR: number;
  /** How deep its first step is, so the loop node can stand level with it. */
  firstSr: number;
  settle: (originO: number, originR: number) => void;
}

/** What a level places: a step, a loop with its body, or the slot of an edge passing through. */
interface Item { so: number; sr: number; anchor: number; body?: Level; bodyO?: number; bodyR?: number }

/** A loop node's width: its summary's, in the monospace it is drawn in. */
export function loopWidth(summary: string, name: string): number {
  return Math.min(SIZE.loopWidest, Math.max(SIZE.nodeWidth, 24 + 6.5 * summary.length, 24 + 7.8 * name.length));
}

export function layoutOf(graph: StepGraph, direction: Direction = "down"): GraphLayout {
  const down = direction === "down";
  const gap = LAYER_GAP[direction];
  const sizeOf = (id: string) => {
    const node = graph.nodes[id];
    const w = node.loop ? loopWidth(node.summary, node.name) : SIZE.nodeWidth;
    const h = node.loop ? SIZE.loopHeight : SIZE.nodeHeight;
    return down ? { so: w, sr: h } : { so: h, sr: w };
  };

  const rects = new Map<string, Rect>();
  const routes: Route[] = [];
  const mid = (a: Point, b: Point): Point => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];

  const level = (container: string | null): Level => {
    const ids = container === null ? graph.top : graph.nodes[container].children;
    const item = new Map<string, Item>();
    for (const id of ids) {
      const s = sizeOf(id);
      if (!graph.nodes[id].loop) { item.set(id, { ...s, anchor: s.so / 2 }); continue; }
      const body = level(id);
      const bodyO = s.so + SIZE.gutter - body.minO;
      const bodyR = Math.max(0, (s.sr - body.firstSr) / 2);
      item.set(id, { so: bodyO + body.maxO, sr: Math.max(s.sr, bodyR + body.maxR), anchor: s.so / 2, body, bodyO, bodyR });
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

    const forward: FlowEdge[] = [];
    const ending: FlowEdge[] = [];                                  // Continue, to this level's loop
    for (const edge of graph.edges) {
      if (edge.enter) continue;
      if (edge.toLoop) { if (edge.to === container && ids.includes(edge.from)) ending.push(edge); continue; }
      const a = childOf(edge.from), b = childOf(edge.to);
      // Both ends stand on this level: a body is left only by `Continue` or by its loop's own exit.
      if (!a || !b || a === b || a !== edge.from) continue;
      forward.push(edge);
    }

    // Longest-path layering over the forward edges, which close no cycle: a bundle's only cycles
    // are its loop nodes, and the compiler refuses any other (`cycle_without_loop`).
    const preds = new Map<string, string[]>(ids.map((id) => [id, []]));
    for (const e of forward) if (!preds.get(e.to)!.includes(e.from)) preds.get(e.to)!.push(e.from);
    const layerOf = new Map<string, number>();
    const depth = (id: string): number => {
      const known = layerOf.get(id);
      if (known !== undefined) return known;
      layerOf.set(id, 0);
      const d = Math.max(-1, ...preds.get(id)!.map(depth)) + 1;
      layerOf.set(id, d);
      return d;
    };
    for (const id of ids) depth(id);

    // An edge that skips layers gets a slim slot in each layer it crosses, ordered and placed like a node.
    const chains = new Map<string, string[]>();
    for (const e of forward) {
      const span = layerOf.get(e.to)! - layerOf.get(e.from)!;
      if (span <= 1) continue;
      const dummies: string[] = [];
      let previous = e.from;
      for (let k = 1; k < span; k++) {
        const id = `\u0000${e.key}#${k}`;
        dummies.push(id);
        layerOf.set(id, layerOf.get(e.from)! + k);
        item.set(id, { so: SIZE.dummy, sr: 0, anchor: SIZE.dummy / 2 });
        preds.set(id, [previous]);
        previous = id;
      }
      preds.set(e.to, preds.get(e.to)!.map((p) => (p === e.from ? previous : p)));
      chains.set(e.key, dummies);
    }
    const all = [...ids, ...[...chains.values()].flat()];

    // Order within a layer by the mean position of its predecessors. Ties: a step that ends the pass
    // stands on the loop's side, so its way back crosses nothing; then written order.
    const ends = new Set(ending.map((e) => e.from));
    const layers: string[][] = [];
    for (const id of all) (layers[layerOf.get(id)!] ??= []).push(id);
    const position = new Map<string, number>();
    layers.forEach((layer, i) => {
      if (i > 0) {
        const bary = (id: string) => {
          const before = preds.get(id)!.map((p) => position.get(p)).filter((v): v is number => v !== undefined);
          return before.length ? before.reduce((a, b) => a + b, 0) / before.length : Number.POSITIVE_INFINITY;
        };
        layer.sort((a, b) => bary(a) - bary(b) || Number(ends.has(b)) - Number(ends.has(a)) || all.indexOf(a) - all.indexOf(b));
      }
      layer.forEach((id, j) => position.set(id, j));
    });

    // Placement: a layer is as deep as its deepest item. One item stands on the axis (a loop by its
    // loop node, its body off to the side); several are centred across it.
    const layerSize = layers.map((layer) => Math.max(0, ...layer.map((id) => item.get(id)!.sr)));
    const layerR: number[] = [];
    layers.forEach((_, i) => { layerR[i] = i === 0 ? 0 : layerR[i - 1] + layerSize[i - 1] + gap; });
    const at = new Map<string, { o: number; r: number; layer: number }>();
    layers.forEach((layer, i) => {
      const width = layer.reduce((w, id) => w + item.get(id)!.so, 0) + (layer.length - 1) * SIZE.nodeGap;
      let o = layer.length === 1 ? -item.get(layer[0])!.anchor : -width / 2;
      for (const id of layer) {
        at.set(id, { o, r: layerR[i], layer: i });
        o += item.get(id)!.so + SIZE.nodeGap;
      }
    });

    // Rails. `Continue` comes back on the loop's side of the body, the step nearest the loop on the
    // rail nearest the body, so no way back crosses another.
    const lowest = Math.min(0, ...all.map((id) => at.get(id)!.o));
    ending.sort((x, y) => at.get(x.from)!.layer - at.get(y.from)!.layer);
    const endRail = new Map<string, { o: number; lane: number }>(ending.map((e, lane) => [e.key, { o: lowest - SIZE.rail * (1 + lane), lane }]));
    const railOs = [...endRail.values()].map((r) => r.o);

    const settle = (originO: number, originR: number) => {
      for (const id of ids) {
        const p = at.get(id)!, it = item.get(id)!;
        rects.set(id, { o: originO + p.o, r: originR + p.r, ...sizeOf(id) });
        if (it.body) it.body.settle(originO + p.o + it.bodyO!, originR + p.r + it.bodyR!);
      }

      for (const e of forward) {
        const a = rects.get(e.from)!, b = rects.get(e.to)!;
        const points: Point[] = [[a.o + a.so / 2, a.r + a.sr]];
        for (const d of chains.get(e.key) ?? []) {
          const p = at.get(d)!, o = originO + p.o + SIZE.dummy / 2;
          points.push([o, originR + layerR[p.layer]], [o, originR + layerR[p.layer] + layerSize[p.layer]]);
        }
        points.push([b.o + b.so / 2, b.r]);
        // A bent edge is labelled on its middle segment, which runs through a slot no node occupies.
        const i = points.length === 2 ? 1 : Math.floor(points.length / 2);
        routes.push({ edge: e, rail: false, points, label: mid(points[i - 1], points[i]), anchor: "middle" });
      }

      if (container !== null && ids.length > 0) {
        // The loop node's far side: the way in near its start, the ways back after it.
        const loop = rects.get(container)!, first = rects.get(ids[0])!;
        const side = loop.o + loop.so;
        const enterR = first.r + first.sr * 0.35;
        const enter = graph.edges.find((e) => e.enter && e.from === container);
        if (enter) routes.push({ edge: enter, rail: false, points: [[side, enterR], [first.o, enterR]], label: mid([side, enterR], [first.o, enterR]), anchor: "middle" });

        for (const e of ending) {
          const rail = endRail.get(e.key)!, s = rects.get(e.from)!, p = at.get(e.from)!;
          const o = originO + rail.o;
          const arrive = Math.min(loop.r + loop.sr - 6, enterR + 13 * (rail.lane + 1));
          const blocked = graph.nodes[e.from].loop || layers[p.layer].some((id) => at.get(id)!.o < p.o);
          let points: Point[], label: Point, anchor: Route["anchor"] = "middle";
          if (e.from === ids[0] && !blocked) {
            // The body's first step: straight back, beside the way in. Its label has the gutter to itself.
            points = [[s.o, arrive], [side, arrive]];
            label = down ? [(s.o + side) / 2, arrive + 12] : [s.o + (side - s.o) / 2, arrive + 6];
            if (!down) anchor = "start";
          } else if (blocked) {
            // A loop leaves by its end, and so does a step with another between it and the rail:
            // out under the layer, across to the rail, back along it.
            const under = s.r + s.sr + gap / 3, c = s.o + s.so / 2;
            points = [[c, s.r + s.sr], [c, under], [o, under], [o, arrive], [side, arrive]];
            label = down ? [(c + o) / 2, under + 11] : mid(points[2], points[3]);
          } else {
            const r = s.r + s.sr / 2;
            points = [[s.o, r], [o, r], [o, arrive], [side, arrive]];
            // Top-down the label stands beside the rail in the gap above the step's layer, where no node is.
            label = down ? [o + 5, s.r - gap / 2] : mid(points[1], points[2]);
            if (down) anchor = "start";
          }
          routes.push({ edge: e, rail: true, points, label, anchor });
        }
      }
    };

    return {
      minO: Math.min(lowest, ...railOs),
      maxO: Math.max(0, ...all.map((id) => at.get(id)!.o + item.get(id)!.so), ...railOs),
      maxR: layers.length ? layerR[layers.length - 1] + layerSize[layers.length - 1] : 0,
      firstSr: ids.length ? sizeOf(ids[0]).sr : 0,
      settle,
    };
  };

  const top = level(null);
  top.settle(-top.minO, 0);

  const page = ([o, r]: Point): Point => (down ? [o, r] : [r, o]);
  const boxes: Record<string, Box> = {};
  for (const [id, rect] of rects) {
    const [x, y] = page([rect.o, rect.r]);
    boxes[id] = down ? { x, y, w: rect.so, h: rect.sr } : { x, y, w: rect.sr, h: rect.so };
  }
  // In the order the model lists them, whichever level placed them.
  const placed = new Map(routes.map((r) => [r.edge.key, r]));
  const edges: PlacedEdge[] = [];
  for (const edge of graph.edges) {
    const r = placed.get(edge.key);
    if (r) edges.push({ edge, rail: r.rail, points: r.points.map(page), label: page(r.label), anchor: r.anchor });
  }
  const [width, height] = page([top.maxO - top.minO, top.maxR]);
  return { direction, boxes, edges, width, height };
}
