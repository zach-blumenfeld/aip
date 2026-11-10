// Where the canvas's cards, frames and wires go. One column in written order, a loop's body inset in
// its frame, every wire leaving a port on the right edge, running down (or up) a lane of its own in the
// gutter to the right of everything, and arriving at the right edge of its target. Drawn to the right
// instead, it is one row: a loop's body is a row inside its frame, and the wires run in a gutter
// under everything and rise into the bottom edge of their targets. The sizes are fixed
// numbers that canvas.css repeats (a card's rows are one line each, clipped), so the layout is known
// without measuring the DOM, and the same model always draws the same picture. No imports but the
// model and no DOM: it runs under node as it is (test/canvas.test.ts).

import type { Card, Frame, Model, Port } from "./model.ts";

export const SIZE = {
  cardWidth: 320,
  pad: 10,          // a card's padding
  head: 24,         // the kind badge and the step's name
  title: 40,        // the description: two lines, clipped
  sectionGap: 6,    // above each section
  row: 18,          // one row of a section, and its label
  port: 22,         // one port
  gap: 22,          // between items of a column
  rowGap: 48,       // between items of a row: the wires leave through it
  inset: 16,        // a frame's body from its sides
  frameHead: 34,    // a frame's header
  gutter: 18,       // from the widest item to the first lane
  lane: 10,         // between lanes
  margin: 12,       // around the whole picture
};

export interface Box { x: number; y: number; w: number; h: number }

export interface Wire {
  from: string;
  /** Which of the source's ports. */
  port: number;
  to: string;
  kind: Port["kind"];
  /** An SVG path, in the layout's coordinates. */
  path: string;
}

export interface Layout {
  boxes: Record<string, Box>;
  /** For each card and frame, the y of each of its ports (their middles). */
  portY: Record<string, number[]>;
  wires: Wire[];
  width: number;
  height: number;
}

/** How tall a card's sections are, above its ports. */
export function bodyHeight(card: Card): number {
  let h = SIZE.pad + SIZE.head + SIZE.title;
  for (const section of card.sections) h += SIZE.sectionGap + SIZE.row * (1 + section.rows.length);
  return h;
}

export function cardHeight(card: Card): number {
  return bodyHeight(card) + (card.ports.length ? SIZE.sectionGap + SIZE.port * card.ports.length : 0) + SIZE.pad;
}

const footHeight = (frame: Frame) => (frame.ports.length ? SIZE.port * frame.ports.length + 8 : SIZE.inset);

export type Direction = "down" | "right";

export function layoutOf(model: Model, direction: Direction = "down"): Layout {
  return direction === "right" ? rowLayout(model) : columnLayout(model);
}

function columnLayout(model: Model): Layout {
  const boxes: Record<string, Box> = {};
  const portY: Record<string, number[]> = {};

  /** Place `ids` as a column with its top left at (x, y); the column's width and height. */
  const column = (ids: string[], x: number, y: number): { w: number; h: number } => {
    let w = 0;
    let cursor = y;
    ids.forEach((id, i) => {
      if (i > 0) cursor += SIZE.gap;
      const size = place(id, x, cursor);
      w = Math.max(w, size.w);
      cursor += size.h;
    });
    return { w, h: cursor - y };
  };

  const place = (id: string, x: number, y: number): { w: number; h: number } => {
    const card = model.cards[id];
    if (card) {
      const h = cardHeight(card);
      boxes[id] = { x, y, w: SIZE.cardWidth, h };
      const first = y + bodyHeight(card) + SIZE.sectionGap + SIZE.port / 2;
      portY[id] = card.ports.map((_, i) => first + i * SIZE.port);
      return { w: SIZE.cardWidth, h };
    }
    const frame = model.frames[id];
    if (!frame) return { w: 0, h: 0 };
    const body = column(frame.children, x + SIZE.inset, y + SIZE.frameHead);
    const w = Math.max(body.w, SIZE.cardWidth) + 2 * SIZE.inset;
    const foot = footHeight(frame);
    const h = SIZE.frameHead + body.h + foot;
    boxes[id] = { x, y, w, h };
    const first = y + SIZE.frameHead + body.h + 4 + SIZE.port / 2;
    portY[id] = frame.ports.map((_, i) => first + i * SIZE.port);
    return { w, h };
  };

  const all = column(model.top, SIZE.margin, SIZE.margin);
  const right = SIZE.margin + all.w;

  // Each wire gets a lane no wire it overlaps has: shortest first, so short hops stay close in.
  const pending: { from: string; port: number; to: string; kind: Port["kind"]; y1: number; y2: number }[] = [];
  const sources: (Card | Frame)[] = [...Object.values(model.cards), ...Object.values(model.frames)];
  for (const source of sources) {
    source.ports.forEach((port, i) => {
      const target = boxes[port.target];
      const ys = portY[source.id];
      if (!target || !ys) return;
      pending.push({ from: source.id, port: i, to: port.target, kind: port.kind, y1: ys[i], y2: target.y + 14 });
    });
  }
  pending.sort((a, b) => Math.abs(a.y2 - a.y1) - Math.abs(b.y2 - b.y1) || a.y1 - b.y1);
  const lanes: { top: number; bottom: number }[][] = [];
  const wires: Wire[] = [];
  for (const w of pending) {
    const top = Math.min(w.y1, w.y2) - 4, bottom = Math.max(w.y1, w.y2) + 4;
    let lane = lanes.findIndex((taken) => taken.every((t) => bottom < t.top || top > t.bottom));
    if (lane < 0) { lanes.push([]); lane = lanes.length - 1; }
    lanes[lane].push({ top, bottom });
    const sx = boxes[w.from].x + boxes[w.from].w;
    const tx = boxes[w.to].x + boxes[w.to].w;
    const gx = right + SIZE.gutter + lane * SIZE.lane;
    wires.push({ from: w.from, port: w.port, to: w.to, kind: w.kind, path: `M ${sx} ${w.y1} H ${gx} V ${w.y2} H ${tx + 7}` });
  }

  return {
    boxes, portY, wires,
    width: right + SIZE.gutter + Math.max(lanes.length, 1) * SIZE.lane + SIZE.margin,
    height: all.h + 2 * SIZE.margin,
  };
}

function rowLayout(model: Model): Layout {
  const boxes: Record<string, Box> = {};
  const portY: Record<string, number[]> = {};

  /** Place `ids` as a row with its top left at (x, y); the row's width and height. */
  const row = (ids: string[], x: number, y: number): { w: number; h: number } => {
    let h = 0;
    let cursor = x;
    ids.forEach((id, i) => {
      if (i > 0) cursor += SIZE.rowGap;
      const size = place(id, cursor, y);
      h = Math.max(h, size.h);
      cursor += size.w;
    });
    return { w: cursor - x, h };
  };

  const place = (id: string, x: number, y: number): { w: number; h: number } => {
    const card = model.cards[id];
    if (card) {
      const h = cardHeight(card);
      boxes[id] = { x, y, w: SIZE.cardWidth, h };
      const first = y + bodyHeight(card) + SIZE.sectionGap + SIZE.port / 2;
      portY[id] = card.ports.map((_, i) => first + i * SIZE.port);
      return { w: SIZE.cardWidth, h };
    }
    const frame = model.frames[id];
    if (!frame) return { w: 0, h: 0 };
    // The body's last wire leaves through the frame's right side, as a card's does through the gap.
    const body = row(frame.children, x + SIZE.inset, y + SIZE.frameHead);
    const w = Math.max(body.w, SIZE.cardWidth) + SIZE.inset + SIZE.rowGap;
    const h = SIZE.frameHead + body.h + footHeight(frame);
    boxes[id] = { x, y, w, h };
    const first = y + SIZE.frameHead + body.h + 4 + SIZE.port / 2;
    portY[id] = frame.ports.map((_, i) => first + i * SIZE.port);
    return { w, h };
  };

  const all = row(model.top, SIZE.margin, SIZE.margin);
  const bottom = SIZE.margin + all.h;

  // Each wire drops from its port to a lane under everything, runs along it, and rises into the
  // bottom edge of its target: shortest first, so short hops stay close in.
  const pending: { from: string; port: number; to: string; kind: Port["kind"]; x0: number; x1: number; y1: number; x2: number; y2: number }[] = [];
  const sources: (Card | Frame)[] = [...Object.values(model.cards), ...Object.values(model.frames)];
  for (const source of sources) {
    source.ports.forEach((port, i) => {
      const target = boxes[port.target];
      const ys = portY[source.id];
      const box = boxes[source.id];
      if (!target || !ys || !box) return;
      const x0 = box.x + box.w;
      pending.push({ from: source.id, port: i, to: port.target, kind: port.kind, x0, x1: x0 + 8 + (i % 6) * 6, y1: ys[i],
                     x2: target.x + 24, y2: target.y + target.h });
    });
  }
  pending.sort((a, b) => Math.abs(a.x2 - a.x1) - Math.abs(b.x2 - b.x1) || a.x1 - b.x1);
  const lanes: { left: number; right: number }[][] = [];
  const wires: Wire[] = [];
  for (const w of pending) {
    const left = Math.min(w.x1, w.x2) - 4, right = Math.max(w.x1, w.x2) + 4;
    let lane = lanes.findIndex((taken) => taken.every((t) => right < t.left || left > t.right));
    if (lane < 0) { lanes.push([]); lane = lanes.length - 1; }
    lanes[lane].push({ left, right });
    const gy = bottom + SIZE.gutter + lane * SIZE.lane;
    wires.push({ from: w.from, port: w.port, to: w.to, kind: w.kind, path: `M ${w.x0} ${w.y1} H ${w.x1} V ${gy} H ${w.x2} V ${w.y2 + 7}` });
  }

  return {
    boxes, portY, wires,
    width: all.w + 2 * SIZE.margin + SIZE.rowGap,
    height: bottom + SIZE.gutter + Math.max(lanes.length, 1) * SIZE.lane + SIZE.margin,
  };
}

/** How deep a card or frame sits: 0 at the top, 1 inside one loop. Frames are drawn outermost first. */
export function depthOf(model: Model, id: string): number {
  let depth = 0;
  let parent = (model.cards[id] ?? model.frames[id])?.parent ?? null;
  while (parent !== null && depth < 64) {
    depth += 1;
    parent = model.frames[parent]?.parent ?? null;
  }
  return depth;
}
